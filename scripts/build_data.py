"""将固定版本的 PokeAPI 官方 CSV 缓存为可追溯的本地图鉴。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PINNED_COMMIT = "2bf639e5572812a67d2b94903fdcb9d095f5aeb2"
MAX_SPECIES = 1025
FILES = (
    "languages.csv", "pokemon.csv", "pokemon_species.csv",
    "pokemon_species_names.csv", "pokemon_species_flavor_text.csv",
    "pokemon_stats.csv", "pokemon_types.csv", "types.csv", "type_names.csv",
    "type_efficacy.csv", "abilities.csv", "ability_names.csv",
    "ability_prose.csv", "ability_flavor_text.csv", "pokemon_abilities.csv",
    "versions.csv", "version_names.csv",
)
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE pokemon (
 id INTEGER PRIMARY KEY, name TEXT, name_en TEXT, genus TEXT,
 generation INTEGER, height REAL, weight REAL,
 hp INTEGER, attack INTEGER, defense INTEGER, sp_attack INTEGER,
 sp_defense INTEGER, speed INTEGER, total INTEGER,
 is_legendary INTEGER, is_mythical INTEGER, evolves_from INTEGER,
 description TEXT, description_language TEXT, description_version TEXT,
 source_url TEXT, artwork TEXT, evolution_hint TEXT
);
CREATE TABLE types (id INTEGER PRIMARY KEY, name TEXT, name_en TEXT);
CREATE TABLE pokemon_type (
 pokemon_id INTEGER REFERENCES pokemon(id), type_id INTEGER REFERENCES types(id),
 slot INTEGER, PRIMARY KEY(pokemon_id, type_id)
);
CREATE TABLE efficacy (
 attack INTEGER REFERENCES types(id), defense INTEGER REFERENCES types(id),
 factor REAL, PRIMARY KEY(attack, defense)
);
CREATE TABLE abilities (
 id INTEGER PRIMARY KEY, name TEXT, name_en TEXT, effect TEXT, language TEXT
);
CREATE TABLE pokemon_ability (
 pokemon_id INTEGER REFERENCES pokemon(id), ability_id INTEGER REFERENCES abilities(id),
 is_hidden INTEGER, PRIMARY KEY(pokemon_id, ability_id)
);
CREATE TABLE documents (
 id TEXT PRIMARY KEY, pokemon_id INTEGER REFERENCES pokemon(id),
 kind TEXT, title TEXT, text TEXT, url TEXT, language TEXT
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX idx_pokemon_generation ON pokemon(generation);
CREATE INDEX idx_pokemon_type_type ON pokemon_type(type_id);
CREATE INDEX idx_pokemon_ability_ability ON pokemon_ability(ability_id);
CREATE INDEX idx_documents_pokemon ON documents(pokemon_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "PokemonCourseResearch/1.0 (local cache)"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                return response.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("下载失败")


def load_sources(data_dir: Path, commit: str) -> tuple[dict, dict]:
    raw_dir = data_dir / "raw" / commit
    raw_dir.mkdir(parents=True, exist_ok=True)
    records_path = raw_dir / "download_manifest.json"
    records = json.loads(records_path.read_text(encoding="utf-8")) if records_path.exists() else {}
    tables = {}
    for filename in FILES:
        path = raw_dir / filename
        url = f"https://raw.githubusercontent.com/PokeAPI/pokeapi/{commit}/data/v2/csv/{filename}"
        if not path.exists():
            payload = download(url)
            path.write_bytes(payload)
            records[filename] = {"url": url, "downloaded_at_utc": utc_now()}
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        previous = records.get(filename, {})
        if previous.get("sha256") and previous["sha256"] != digest:
            raise ValueError(f"缓存校验失败，请检查文件：{path}")
        records[filename] = {
            **previous, "url": url, "sha256": digest, "bytes": len(payload),
            "path": path.relative_to(data_dir).as_posix(),
        }
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            tables[filename] = list(csv.DictReader(handle))
        print(f"cached {filename}: {len(tables[filename])} rows", flush=True)
    return tables, records


def localized(rows: list[dict], key: str) -> dict[int, dict]:
    selected = {}
    for language in (9, 12):
        for row in rows:
            if int(row["local_language_id"]) == language:
                selected[int(row[key])] = row
    return selected


def clean_text(value: str) -> str:
    return " ".join(value.replace("\f", " ").split())


def chosen_text(rows: list[dict], key: str, language_key: str, version_key: str) -> dict[int, dict]:
    selected = {}
    for row in sorted(rows, key=lambda item: int(item[version_key])):
        language = int(row[language_key])
        if language not in (9, 12):
            continue
        entity = int(row[key])
        previous = selected.get(entity)
        if previous is None or language == 12 or int(previous[language_key]) != 12:
            selected[entity] = row
    return selected


def build(data_dir: Path, commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit 必须为完整的 40 位 Git 提交哈希")
    tables, downloads = load_sources(data_dir, commit)
    languages = {int(row["id"]): row["identifier"] for row in tables["languages.csv"]}
    assert languages[12] == "zh-hans" and languages[9] == "en"
    species = {
        int(row["id"]): row for row in tables["pokemon_species.csv"]
        if int(row["id"]) <= MAX_SPECIES and int(row["generation_id"]) <= 9
    }
    defaults = {
        int(row["species_id"]): row for row in tables["pokemon.csv"]
        if row["is_default"] == "1" and int(row["species_id"]) in species
    }
    assert set(defaults) == set(range(1, MAX_SPECIES + 1)), "默认形态未覆盖 1–1025"
    names = localized(tables["pokemon_species_names.csv"], "pokemon_species_id")
    type_names = localized(tables["type_names.csv"], "type_id")
    ability_names = localized(tables["ability_names.csv"], "ability_id")
    version_names = localized(tables["version_names.csv"], "version_id")
    versions = {int(row["id"]): row["identifier"] for row in tables["versions.csv"]}
    descriptions = chosen_text(tables["pokemon_species_flavor_text.csv"], "species_id", "language_id", "version_id")
    ability_flavor = chosen_text(tables["ability_flavor_text.csv"], "ability_id", "language_id", "version_group_id")
    ability_prose = localized(tables["ability_prose.csv"], "ability_id")
    stats = defaultdict(dict)
    for row in tables["pokemon_stats.csv"]:
        stats[int(row["pokemon_id"])][int(row["stat_id"])] = int(row["base_stat"])
    pokemon_types = defaultdict(list)
    for row in tables["pokemon_types.csv"]:
        if 1 <= int(row["type_id"]) <= 18:
            pokemon_types[int(row["pokemon_id"])].append((int(row["type_id"]), int(row["slot"])))
    pokemon_abilities = defaultdict(list)
    for row in tables["pokemon_abilities.csv"]:
        pokemon_abilities[int(row["pokemon_id"])].append((int(row["ability_id"]), int(row["is_hidden"])))

    db_path = data_dir / "pokedex.sqlite"
    temporary = data_dir / "pokedex.building.sqlite"
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    connection.executescript(SCHEMA)
    selected_types = {int(row["id"]): row for row in tables["types.csv"] if 1 <= int(row["id"]) <= 18}
    for type_id, row in selected_types.items():
        connection.execute("INSERT INTO types VALUES (?, ?, ?)", (type_id, type_names[type_id]["name"], row["identifier"]))
    for row in tables["type_efficacy.csv"]:
        attack, defense = int(row["damage_type_id"]), int(row["target_type_id"])
        if attack in selected_types and defense in selected_types:
            connection.execute("INSERT INTO efficacy VALUES (?, ?, ?)", (attack, defense, int(row["damage_factor"]) / 100))

    used_abilities = {ability for row in defaults.values() for ability, _ in pokemon_abilities[int(row["id"])]}
    ability_texts = {}
    for row in tables["abilities.csv"]:
        ability_id = int(row["id"])
        if ability_id not in used_abilities:
            continue
        flavor = ability_flavor.get(ability_id, {})
        prose = ability_prose.get(ability_id, {})
        if flavor.get("language_id") == "12":
            effect, language = clean_text(flavor["flavor_text"]), "zh-hans"
        elif prose:
            effect, language = clean_text(prose["short_effect"] or prose["effect"]), languages[int(prose["local_language_id"])]
        elif flavor:
            effect, language = clean_text(flavor["flavor_text"]), languages[int(flavor["language_id"])]
        else:
            effect, language = "", "und"
        name = ability_names.get(ability_id, {}).get("name", row["identifier"])
        ability_texts[ability_id] = (name, effect)
        connection.execute("INSERT INTO abilities VALUES (?, ?, ?, ?, ?)", (ability_id, name, row["identifier"], effect, language))
        connection.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)", (
            f"ability:{ability_id}", None, "ability", f"特性：{name}",
            f"{name} ({row['identifier']})。{effect}", f"https://pokeapi.co/api/v2/ability/{ability_id}/", language,
        ))

    description_counts = Counter()
    name_counts = Counter()
    missing_descriptions = []
    for species_id, source in sorted(species.items()):
        pokemon = defaults[species_id]
        source_id = int(pokemon["id"])
        assert set(stats[source_id]) == set(range(1, 7)), f"种族值缺失：{species_id}"
        assert pokemon_types[source_id], f"属性缺失：{species_id}"
        name_row = names.get(species_id, {})
        name = name_row.get("name", source["identifier"])
        genus = name_row.get("genus", "")
        name_counts[languages.get(int(name_row.get("local_language_id", 0)), "und")] += 1
        flavor = descriptions.get(species_id, {})
        description = clean_text(flavor.get("flavor_text", ""))
        language = languages[int(flavor["language_id"])] if flavor else "und"
        version_id = int(flavor["version_id"]) if flavor else None
        version = version_names.get(version_id, {}).get("name", versions.get(version_id, ""))
        if not description:
            missing_descriptions.append(species_id)
        description_counts[language] += 1
        evolves_from = int(source["evolves_from_species_id"]) if source["evolves_from_species_id"] else None
        evolution_hint = f"由{names[evolves_from]['name']}进化而来；具体条件未纳入当前快照。" if evolves_from else "无前置进化物种记录；不代表没有后续进化。"
        values = [stats[source_id][stat] for stat in range(1, 7)]
        source_url = f"https://pokeapi.co/api/v2/pokemon/{source_id}/"
        species_url = f"https://pokeapi.co/api/v2/pokemon-species/{species_id}/"
        artwork = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{source_id}.png"
        connection.execute("INSERT INTO pokemon VALUES (" + ",".join("?" * 23) + ")", (
            species_id, name, source["identifier"], genus, int(source["generation_id"]),
            int(pokemon["height"]) / 10, int(pokemon["weight"]) / 10, *values, sum(values),
            int(source["is_legendary"]), int(source["is_mythical"]), evolves_from,
            description, language, version, source_url, artwork, evolution_hint,
        ))
        for type_id, slot in pokemon_types[source_id]:
            connection.execute("INSERT INTO pokemon_type VALUES (?, ?, ?)", (species_id, type_id, slot))
        for ability_id, hidden in pokemon_abilities[source_id]:
            connection.execute("INSERT INTO pokemon_ability VALUES (?, ?, ?)", (species_id, ability_id, hidden))
        types_text = " / ".join(type_names[type_id]["name"] for type_id, _ in sorted(pokemon_types[source_id], key=lambda item: item[1]))
        abilities_text = "、".join(ability_texts[ability][0] + ("（隐藏特性）" if hidden else "") for ability, hidden in pokemon_abilities[source_id])
        text = (
            f"{name} ({source['identifier']})，全国图鉴编号 {species_id}，第{source['generation_id']}世代。"
            f"{genus}。属性：{types_text}。身高 {int(pokemon['height']) / 10:g} 米，体重 {int(pokemon['weight']) / 10:g} 千克。"
            f"种族值：HP {values[0]}、攻击 {values[1]}、防御 {values[2]}、特攻 {values[3]}、特防 {values[4]}、速度 {values[5]}，总和 {sum(values)}。"
            f"特性：{abilities_text}。"
        )
        connection.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)", (f"pokemon:{species_id}", species_id, "pokemon", name, text, source_url, "zh-hans"))
        description_text = (
            f"{name} ({source['identifier']})。{evolution_hint}"
            f"图鉴描述（{version or '版本未知'}，{language}）：{description or '此快照未收录可用的中英文描述。'}"
        )
        connection.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)", (
            f"description:{species_id}", species_id, "description", f"{name}的图鉴描述", description_text,
            species_url, "zh-hans" if language == "zh-hans" else f"zh-hans+{language}",
        ))

    manifest = {
        "schema_version": 1,
        "built_at_utc": utc_now(),
        "repository": "https://github.com/PokeAPI/pokeapi",
        "commit": commit,
        "commit_url": f"https://github.com/PokeAPI/pokeapi/commit/{commit}",
        "scope": {"species_min": 1, "species_max": MAX_SPECIES, "species_count": len(species), "generations": [1, 9], "forms": "default only", "type_count": 18, "efficacy_rows": 324},
        "language_policy": "Prefer zh-hans (12); fallback en (9); preserve missing values and per-record language.",
        "name_languages": dict(name_counts),
        "description_languages": dict(description_counts),
        "missing_description_species": missing_descriptions,
        "ability_count": len(used_abilities),
        "ability_languages": dict(connection.execute("SELECT language, COUNT(*) FROM abilities GROUP BY language").fetchall()),
        "document_count": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "sources": downloads,
        "limitations": [
            "Current repository snapshot, not a game-version-specific legality database.",
            "Only default forms, species 1–1025; regional/Mega/Gigantamax forms excluded.",
            "18 conventional types; Stellar, abilities, weather, items and moves are not part of type-efficacy calculation.",
            "Evolution parent relations only; branching conditions are not imported.",
            "Artwork URLs refer to the external sprites repository master branch and are not frozen in this snapshot.",
            "Localized descriptions may come from different game versions; inspect description_version and language.",
            "API source links identify records; reproducible evidence is the pinned raw CSV snapshot.",
        ],
    }
    connection.executemany("INSERT INTO metadata VALUES (?, ?)", [(key, json.dumps(value, ensure_ascii=False)) for key, value in manifest.items()])
    connection.commit()
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    assert connection.execute("SELECT COUNT(*) FROM efficacy").fetchone()[0] == 324
    connection.close()
    temporary.replace(db_path)
    manifest["database_sha256"] = hashlib.sha256(db_path.read_bytes()).hexdigest()
    (data_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("commit", "scope", "description_languages", "ability_count", "document_count", "database_sha256")}, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default=PINNED_COMMIT, help="PokeAPI 仓库完整提交哈希，默认使用已核验快照")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    arguments = parser.parse_args()
    build(arguments.data_dir, arguments.commit)
