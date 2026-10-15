"""Small trusted fixtures. Reference patches never enter the model's repo."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Benchmark:
    name: str
    task: str
    filename: str
    source: str
    tests: str
    old: str
    new: str
    holdout_tests: str = ""


BENCHMARKS = (
    Benchmark(
        "shipping_discount", "Fix checkout: discount merchandise, round down, then add full shipping.",
        "pricing.py",
        "def total(items, discount=0, shipping=0):\n"
        "    subtotal = sum(price * quantity for price, quantity in items)\n"
        "    return (subtotal + shipping) * (100 - discount) // 100\n",
        "import unittest\nfrom pricing import total\n"
        "class PricingTests(unittest.TestCase):\n"
        " def test_regular(self): self.assertEqual(total([(1000, 2)], 0, 100), 2100)\n"
        " def test_discount(self): self.assertEqual(total([(1000, 2)], 10, 100), 1900)\n"
        " def test_rounding(self): self.assertEqual(total([(999, 1)], 15, 125), 974)\n"
        " def test_free_items(self): self.assertEqual(total([(999, 1)], 100, 125), 125)\n",
        "return (subtotal + shipping) * (100 - discount) // 100",
        "return subtotal * (100 - discount) // 100 + shipping",
        "import unittest\nfrom pricing import total\n"
        "class HoldoutPricing(unittest.TestCase):\n"
        " def test_combinations(self):\n"
        "  for items in ([], [(1, 1)], [(123, 3), (57, 2)], [(9999, 0)]):\n"
        "   for discount in (0, 1, 33, 99, 100):\n"
        "    for shipping in (0, 1, 499):\n"
        "     with self.subTest(items=items, discount=discount, shipping=shipping):\n"
        "      expected = sum(p*q for p,q in items) * (100-discount) // 100 + shipping\n"
        "      self.assertEqual(total(items, discount, shipping), expected)\n"),
    Benchmark(
        "normalize_slug", "Fix slugify: trim, lowercase, collapse whitespace into single hyphens. Preserve other characters.",
        "slug.py", "def slugify(text):\n    return text.lower().replace(' ', '-')\n",
        "import unittest\nfrom slug import slugify\n"
        "class SlugTests(unittest.TestCase):\n"
        " def test_basic(self): self.assertEqual(slugify('Hello World'), 'hello-world')\n"
        " def test_trim(self): self.assertEqual(slugify('  Hello  World  '), 'hello-world')\n"
        " def test_tabs(self): self.assertEqual(slugify('A\\tB\\nC'), 'a-b-c')\n"
        " def test_empty(self): self.assertEqual(slugify('   '), '')\n"
        " def test_unicode(self): self.assertEqual(slugify(' 台灣 AI '), '台灣-ai')\n",
        "return text.lower().replace(' ', '-')", "return '-'.join(text.lower().split())",
        "import unittest\nfrom slug import slugify\n"
        "class HoldoutSlug(unittest.TestCase):\n"
        " def test_cases(self):\n"
        "  cases = [('', ''), ('A-B_C!', 'a-b_c!'), ('\\t X \\n Y \\t', 'x-y'),\n"
        "           ('A\\u00a0B', 'a-b'), ('ÉCOLE 台灣', 'école-台灣'), ('---', '---')]\n"
        "  for text, expected in cases:\n"
        "   with self.subTest(text=text): self.assertEqual(slugify(text), expected)\n"),
    Benchmark(
        "mean_precision", "Fix mean: return the arithmetic mean without integer truncation; empty input raises ValueError.",
        "stats.py", "def mean(values):\n    return sum(values) // len(values)\n",
        "import unittest\nfrom stats import mean\n"
        "class MeanTests(unittest.TestCase):\n"
        " def test_whole(self): self.assertEqual(mean([2, 4]), 3)\n"
        " def test_fraction(self): self.assertEqual(mean([1, 2]), 1.5)\n"
        " def test_negative(self): self.assertEqual(mean([-2, -1]), -1.5)\n"
        " def test_single(self): self.assertEqual(mean([7]), 7)\n"
        " def test_empty(self):\n"
        "  with self.assertRaises(ValueError): mean([])\n",
        "    return sum(values) // len(values)",
        "    if not values:\n        raise ValueError('empty input')\n    return sum(values) / len(values)",
        "import unittest\nfrom stats import mean\n"
        "class HoldoutMean(unittest.TestCase):\n"
        " def test_cases(self):\n"
        "  for values in ([0], [0, 0], [1, 2, 4], [-7, 0, 3], [0.25, 1.75, 3.5], (2, 3)):\n"
        "   with self.subTest(values=values):\n"
        "    self.assertAlmostEqual(mean(values), sum(values)/len(values))\n"
        " def test_empty(self):\n"
        "  with self.assertRaises(ValueError): mean([])\n"),
)
