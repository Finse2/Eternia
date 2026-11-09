import unittest
from eternia.simulation import World


class SimulationTests(unittest.TestCase):
    def test_year_zero(self):
        w = World(seed=42)
        self.assertEqual(len(w.settlements), 7)
        self.assertEqual(sum(s.population for s in w.settlements), 1000)
        self.assertEqual(len(w.agents), 50)
        self.assertTrue(all(s.knowledge == 0 for s in w.settlements))
        self.assertNotIn('aether', w.settlements[0].public_state())

    def test_repeatable_runs(self):
        a = World(21).run(100).export()
        b = World(21).run(100).export()
        self.assertEqual(a, b)

    def test_world_survives_one_thousand_years(self):
        w = World(seed=42).run(1000)
        self.assertEqual(w.year, 1000)
        self.assertEqual(w.snapshots[-1]['year'], 1000)
        self.assertTrue(all(s.population >= 10 for s in w.settlements))

    def test_no_negative_inventory(self):
        w = World(seed=123).run(300)
        for s in w.settlements:
            self.assertGreaterEqual(min(s.food, s.wood, s.iron, s.treasury), 0)


if __name__ == '__main__':
    unittest.main()
