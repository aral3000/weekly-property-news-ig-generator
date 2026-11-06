import unittest
from generator import (
    lint_caption,
    parse_rss_xml,
    rank_and_deduplicate,
    strip_outlet_suffix,
)

SAMPLE_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>Punya Gaji Rp 8,9 Juta, Apakah Bisa Beli Rumah Impian? - Kompas.com</title>
      <link>https://news.google.com/rss/articles/1</link>
      <pubDate>Tue, 03 Nov 2026 02:00:00 GMT</pubDate>
      <description>&lt;a href="https://news.google.com/1"&gt;Punya Gaji Rp 8,9 Juta&lt;/a&gt;</description>
      <source url="https://www.kompas.com">Kompas.com</source>
    </item>
    <item>
      <title>Gaji Rp 8,9 Juta Membuka Peluang Pekerja Muda Beli Rumah - Demokratis.co.id</title>
      <link>https://news.google.com/rss/articles/2</link>
      <pubDate>Tue, 03 Nov 2026 02:11:23 GMT</pubDate>
      <description>Gaji Rp 8,9 Juta Membuka Peluang Pekerja Muda Beli Rumah</description>
      <source url="https://demokratis.co.id">Demokratis.co.id</source>
    </item>
    <item>
      <title>Mark Zuckerberg Beli Rumah Rp 3,08 Triliun, Bertetangga dengan Jeff Bezos - Kompas.com</title>
      <link>https://news.google.com/rss/articles/3</link>
      <pubDate>Sun, 01 Nov 2026 02:54:00 GMT</pubDate>
      <description>Mark Zuckerberg Beli Rumah</description>
      <source url="https://www.kompas.com">Kompas.com</source>
    </item>
    <item>
      <title>Harga Rumah Australia Anjlok 6,7 Persen dalam Tujuh Bulan - Demokratis.co.id</title>
      <link>https://news.google.com/rss/articles/4</link>
      <pubDate>Mon, 02 Nov 2026 03:00:15 GMT</pubDate>
      <description>Harga Rumah Australia Anjlok</description>
      <source url="https://demokratis.co.id">Demokratis.co.id</source>
    </item>
    <item>
      <title>Harga Rumah Makin Mahal, Rumah Lelang-Rumah Bekas Jadi Alternatif? - CNBC Indonesia</title>
      <link>https://news.google.com/rss/articles/5</link>
      <pubDate>Wed, 04 Nov 2026 04:45:00 GMT</pubDate>
      <description>Rumah Lelang-Rumah Bekas Jadi Alternatif</description>
      <source url="https://www.cnbcindonesia.com">CNBC Indonesia</source>
    </item>
  </channel>
</rss>"""


class TestWeeklyIGGenerator(unittest.TestCase):
    def test_strip_outlet_suffix_removes_trailing_media_name(self) -> None:
        raw = "Warga RI Antre Beli Rumah Subsidi - CNBC Indonesia"
        self.assertEqual(strip_outlet_suffix(raw, "CNBC Indonesia"), "Warga RI Antre Beli Rumah Subsidi")

    def test_parse_rss_xml_extracts_clean_fields(self) -> None:
        items = parse_rss_xml(SAMPLE_RSS_XML)
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0]["source"], "Kompas.com")
        self.assertNotIn(" - Kompas.com", items[0]["title"])
        self.assertNotIn("<a", items[0]["snippet"])

    def test_rank_and_deduplicate_filters_noise_and_syndicated_duplicates(self) -> None:
        items = parse_rss_xml(SAMPLE_RSS_XML)
        ranked = rank_and_deduplicate(items, top_k=3)
        titles = [item["title"] for item in ranked]

        self.assertEqual(len(ranked), 2)
        self.assertTrue(any("Rumah Lelang-Rumah Bekas" in t for t in titles))
        self.assertEqual(sum("8,9" in t for t in titles), 1)
        self.assertFalse(any("Zuckerberg" in t or "Australia" in t for t in titles))

    def test_lint_caption_sanitizes_markdown_and_validates_constraints(self) -> None:
        dirty = (
            "**Gaji Rp 8,9 juta mau ambil KPR pertama tahun ini?**\n\n"
            "Banyak calon pembeli rumah langsung fokus pada DP\u2014padahal cicilan bulanan wajib aman.\n\n"
            "Tiga hitungan dasar sebelum tanda tangan kredit:\n"
            "1. Batasi cicilan KPR maksimal 30% penghasilan bulanan, sekitar Rp 2,6 juta untuk gaji Rp 8,9 juta.\n"
            "2. Siapkan dana darurat plus biaya pra-akad seperti BPHTB, notaris, provisi bank, dan asuransi.\n"
            "3. Bandingkan tenor 15 tahun vs 20 tahun agar beban bunga floating tetap terukur.\n\n"
            "Cek estimasi cicilan bulanan lebih dulu lewat fitur Simulasi KPR di aplikasi atau website Rumah123 "
            "sesuai harga properti, besaran DP, dan pilihan tenor yang kamu incar.\n\n"
            "Dengan gaji Rp 8,9 juta, kamu pilih beli rumah tapak pinggiran dekat KRL atau menabung DP lebih besar? "
            "Save postingan ini dan tulis pendapatmu di komentar!\n\n"
            "#Rumah123 #SimulasiKPR #TipsKPR #BeliRumahPertama #PropertiIndonesia"
        )
        res = lint_caption(dirty)
        self.assertTrue(res["passed"], msg=f"Unexpected lint issues: {res['issues']}")
        self.assertNotIn("**", res["caption"])
        self.assertNotIn("\u2014", res["caption"])
        self.assertEqual(res["metrics"]["hashtag_count"], 5)

    def test_lint_caption_flags_missing_brand_and_excess_hashtags(self) -> None:
        bad = "Hook pendek.\n\n Teks terlalu pendek untuk Anda tanpa merek.\n\n#satu #dua #tiga #empat #lima #enam #tujuh"
        res = lint_caption(bad)
        self.assertFalse(res["passed"])
        self.assertIn("missing_rumah123_mention", res["issues"])
        self.assertIn("formal_pronoun_anda", res["issues"])

    def test_n8n_workflow_json_is_valid_and_secret_free(self) -> None:
        import json
        import re
        from pathlib import Path
        raw = Path(__file__).with_name("workflow.json").read_text(encoding="utf-8")
        wf = json.loads(raw)
        self.assertEqual(len(wf["nodes"]), 8)
        self.assertNotIn("apiKey=", raw)
        self.assertIsNone(re.search(r"[0-9a-f]{32}", raw))


    def test_parse_rss_xml_rejects_doctype_entity_payloads(self) -> None:
        malicious = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><rss><channel></channel></rss>'
        with self.assertRaises(ValueError):
            parse_rss_xml(malicious)


if __name__ == "__main__":
    unittest.main()
