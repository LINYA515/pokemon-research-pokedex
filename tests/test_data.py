"""核对真实快照的覆盖范围、已知事实、语言标记及文件校验值。"""

import hashlib
import json
from pathlib import Path
import sqlite3
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(ROOT / "data" / "pokedex.sqlite")
        cls.connection.row_factory = sqlite3.Row
        cls.manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_coverage_and_integrity(self):
        ids = [row[0] for row in self.connection.execute("SELECT id FROM pokemon ORDER BY id")]
        self.assertEqual(ids, list(range(1, 1026)))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM types").fetchone()[0], 18)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM efficacy").fetchone()[0], 324)
        self.assertEqual(self.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_pikachu_statistics_and_units(self):
        row = self.connection.execute("SELECT * FROM pokemon WHERE id=25").fetchone()
        self.assertEqual(row["name"], "皮卡丘")
        self.assertEqual([row[field] for field in ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")], [35, 55, 40, 50, 50, 90])
        self.assertEqual(row["total"], 320)
        self.assertEqual(row["height"], 0.4)
        self.assertEqual(row["weight"], 6.0)

    def test_quagsire_dual_type_multipliers(self):
        types = self.connection.execute("SELECT t.id,t.name_en FROM pokemon_type p JOIN types t ON t.id=p.type_id WHERE p.pokemon_id=195").fetchall()
        self.assertEqual({row["name_en"] for row in types}, {"water", "ground"})
        for attacker, expected in (("grass", 4.0), ("electric", 0.0)):
            factors = [self.connection.execute("SELECT e.factor FROM efficacy e JOIN types t ON t.id=e.attack WHERE t.name_en=? AND e.defense=?", (attacker, row["id"])).fetchone()[0] for row in types]
            self.assertEqual(factors[0] * factors[1], expected)

    def test_values_documents_and_language_flags(self):
        for row in self.connection.execute("SELECT * FROM pokemon"):
            self.assertEqual(sum(row[field] for field in ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")), row["total"])
            self.assertIn(row["description_language"], ("zh-hans", "en", "und"))
            self.assertTrue(row["source_url"].endswith(f"/{row['id']}/"))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM documents WHERE kind='pokemon'").fetchone()[0], 1025)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM documents WHERE kind='description'").fetchone()[0], 1025)
        self.assertGreater(self.connection.execute("SELECT COUNT(*) FROM documents WHERE kind='ability'").fetchone()[0], 200)

    def test_frozen_download_hashes(self):
        for source in self.manifest["sources"].values():
            path = ROOT / "data" / source["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])
            self.assertIn(self.manifest["commit"], source["url"])
            self.assertIn("downloaded_at_utc", source)
        self.assertEqual(hashlib.sha256((ROOT / "data" / "pokedex.sqlite").read_bytes()).hexdigest(), self.manifest["database_sha256"])


if __name__ == "__main__":
    unittest.main()
