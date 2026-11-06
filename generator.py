import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

DEFAULT_RSS_QUERY = (
    '("suku bunga KPR" OR "harga rumah" OR "pasar properti" '
    'OR "beli rumah" OR "rumah subsidi") when:7d'
)

STOPWORDS_ID = frozenset({
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "untuk", "pada", "dengan",
    "atau", "jadi", "bisa", "akan", "ada", "dalam", "saat", "para", "oleh",
    "apakah", "kenapa", "mengapa", "bagaimana", "masih", "makin", "terus",
    "lebih", "kian", "buka", "membuka", "peluang", "alasan", "alasannya",
})

NEGATIVE_KEYWORDS = frozenset({
    "australia", "portugal", "vietnam", "amerika", "inggris", "jepang", "china",
    "10 negara", "zuckerberg", "bezos", "musk", "artis", "seleb", "suami", "istri",
    "cerai", "pesawat", "penerbangan", "kendaraan listrik", "mobil listrik", "kripto",
})

POSITIVE_KEYWORDS: dict[str, int] = {
    "kpr": 4, "suku bunga": 4, "cicilan": 3, "subsidi": 3, "rumah bekas": 3,
    "rumah lelang": 3, "gaji": 3, "harga rumah": 3, "pasar properti": 3,
    "bphtb": 3, "ppn dtp": 3, "dp": 2, "bank": 2, "kredit": 2, "sewa": 2,
    "ngontrak": 2, "pekerja muda": 2, "milenial": 2, "gen z": 2,
    "jakarta": 2, "bekasi": 2, "bogor": 2, "depok": 2, "tangerang": 2, "ri": 2,
}

TRUSTED_OUTLETS = frozenset({
    "cnbc indonesia", "kompas.com", "bisnis.com", "kontan.co.id", "investor.id",
    "detikcom", "detikfinance", "kumparan", "tempo.co", "liputan6.com", "antaranews.com",
})

SYSTEM_PROMPT = """Kamu adalah Content Strategist dan Edukator Properti untuk akun Instagram resmi Rumah123 (@rumah123com).
Tugasmu: mengubah 1 headline berita properti/KPR mingguan di Indonesia menjadi caption Instagram edukatif yang siap tayang.

Aturan wajib:
1. Kejujuran sumber: input berasal dari RSS headline (judul, media, tanggal tayang), bukan isi artikel penuh. Jika judul berupa kalimat tanya (misalnya "RI Termasuk?"), JANGAN mengklaim kesimpulan isi artikel yang belum dibaca. DILARANG mengarang angka survei, persentase, atau batas gaji tunggal tanpa konteks aturan wilayah dan status pernikahan (misalnya batas gaji MBR KPR Subsidi berbeda antara lajang/menikah serta zona wilayah).
2. Sapaan dan bahasa: wajib gunakan sapaan akrab "kamu" (DILARANG memakai kata kaku "Anda"). Gunakan bahasa Indonesia yang luwes, tajam, dan natural bagi pembeli rumah usia 24-38 tahun.
3. Format plain-text Instagram: DILARANG memakai tanda bintang Markdown (**teks**), pagar heading (#), bullet bintang (*), karakter em-dash, maupun tanda hubung ganda (--). Gunakan penomoran 1., 2., 3. dan baris kosong antarparagraf.
4. Hook baris pertama: maksimal 14 kata, kalimat tanya atau kontras tajam agar pembaca klik tombol "more" sebelum batas 125 karakter.
5. Isi edukasi: berikan 3 poin praktis yang relevan dengan topik berita (misalnya batas aman cicilan maksimal 30% penghasilan bersih bulanan, cek fisik bangunan dan dokumen SHM/IMB saat beli rumah seken atau lelang, persiapan dana pra-akad 8%-10% untuk BPHTB/notaris/provisi KPR, atau pengecekan riwayat SLIK OJK).
6. Integrasi produk: sebutkan secara natural fitur nyata di Rumah123 yang relevan (seperti fitur Simulasi KPR Rumah123 untuk hitung estimasi cicilan dari harga, DP, suku bunga, dan tenor, atau filter pencarian rumah seken dan rumah baru sesuai lokasi dan bujet).
7. Call to Action (CTA): tutup dengan pertanyaan pilihan A vs B yang memancing diskusi di kolom komentar, ditambah ajakan save postingan.
8. Panjang dan hashtag: total 135 sampai 205 kata (di luar hashtag), ditutup tepat 5 hashtag relevan diawali #Rumah123.
9. Larangan klise AI: hindari frasa "hunian impian", "kabar gembira", "solusi terbaik", "di era modern", atau "jangan lewatkan"."""


def build_user_prompt(article: dict[str, str]) -> str:
    return (
        f"Judul berita minggu ini: {article['title']}\n"
        f"Media sumber: {article['source']}\n"
        f"Tanggal publikasi: {article['published_at']}\n\n"
        "Tulis 1 caption Instagram Rumah123 berbahasa Indonesia sesuai seluruh aturan sistem. "
        "Langsung keluarkan teks caption tanpa kata pengantar."
    )


def strip_outlet_suffix(raw_title: str, source: str) -> str:
    cleaned = html.unescape(raw_title).strip()
    if source and cleaned.lower().endswith(f" - {source.lower()}"):
        return cleaned[: -(len(source) + 3)].strip()
    parts = cleaned.rsplit(" - ", 1)
    return parts[0].strip() if len(parts) == 2 and len(parts[1]) < 40 else cleaned


def parse_rss_xml(xml_bytes: bytes) -> list[dict[str, str]]:
    if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise ValueError("Refusing XML payload containing DOCTYPE or ENTITY declarations")
    root = ET.fromstring(xml_bytes)
    articles: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else "Google News"
        raw_title = item.findtext("title", "")
        title = strip_outlet_suffix(raw_title, source)
        link = (item.findtext("link", "") or "").strip()
        pub_date = (item.findtext("pubDate", "") or "").strip()
        raw_desc = item.findtext("description", "") or ""
        desc = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw_desc))).strip()
        if title and link:
            articles.append({
                "title": title,
                "source": source,
                "published_at": pub_date,
                "url": link,
                "snippet": desc,
            })
    return articles


def fetch_rss_articles(query: str = DEFAULT_RSS_QUERY, timeout: int = 15) -> list[dict[str, str]]:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"
    req = urllib.request.Request(url, headers={"User-Agent": "Rumah123WeeklyIGBot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_rss_xml(resp.read(2_000_000))


def tokenize_headline(title: str) -> set[str]:
    lowered = title.lower()
    # Keep Indonesian decimal numbers like 8,9 intact so syndicated salary/rate stories match.
    tokens = re.findall(r"\d+(?:[.,]\d+)?|[a-z]{3,}", lowered)
    return {tok for tok in tokens if tok not in STOPWORDS_ID}


def score_article(article: dict[str, str]) -> int:
    text = f"{article['title']} {article['source']}".lower()
    if any(re.search(rf"\b{re.escape(neg)}\b", text) for neg in NEGATIVE_KEYWORDS):
        return -100
    score = sum(
        weight for kw, weight in POSITIVE_KEYWORDS.items()
        if re.search(rf"\b{re.escape(kw)}\b", text)
    )
    if article["source"].lower() in TRUSTED_OUTLETS:
        score += 4
    return score


def jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def rank_and_deduplicate(
    articles: list[dict[str, str]],
    top_k: int = 3,
    jaccard_threshold: float = 0.32,
    max_per_outlet: int = 2,
) -> list[dict[str, Any]]:
    scored = []
    for art in articles:
        pts = score_article(art)
        if pts > 0:
            scored.append({**art, "relevance_score": pts, "_tokens": tokenize_headline(art["title"])})
    scored.sort(key=lambda x: x["relevance_score"], reverse=True)

    selected: list[dict[str, Any]] = []
    outlet_counts: dict[str, int] = {}
    # ponytail: O(n * k) token Jaccard scan over <=100 weekly RSS items; swap to MinHash if >10k items.
    for candidate in scored:
        outlet = candidate["source"].lower()
        if outlet_counts.get(outlet, 0) >= max_per_outlet:
            continue
        is_dup = any(
            jaccard_similarity(candidate["_tokens"], chosen["_tokens"]) >= jaccard_threshold
            for chosen in selected
        )
        if not is_dup:
            selected.append(candidate)
            outlet_counts[outlet] = outlet_counts.get(outlet, 0) + 1
        if len(selected) >= top_k:
            break

    return [{k: v for k, v in item.items() if k != "_tokens"} for item in selected]


def _call_gemini_rest(system_prompt: str, user_prompt: str, api_key: str) -> str:
    import time
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash").removeprefix("models/")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.35},
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    data: dict[str, Any] = {}
    for attempt in range(4):
        req = urllib.request.Request(
            url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 503) and attempt < 3:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
    candidates = data.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
    texts = [str(p["text"]) for p in (parts or []) if "text" in p and not p.get("thought")]
    if not texts:
        raise RuntimeError(f"Gemini returned empty or blocked response: {data.get('promptFeedback', {})}")
    return "".join(texts).strip()


def _call_openai_compat(system_prompt: str, user_prompt: str, api_key: str, base_url: str, model: str) -> str:
    if not base_url.startswith(("https://", "http://")):
        raise ValueError("OPENAI_BASE_URL must start with https:// or http://")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.35,
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices") or []
    content = (choices[0].get("message") or {}).get("content") if choices else None
    if not content:
        raise RuntimeError("OpenAI-compatible endpoint returned empty content")
    return str(content).strip()


def _fallback_caption(article: dict[str, str]) -> str:
    clean_title = article["title"].rstrip("?!.")
    return (
        "Sempat baca update berita properti dan KPR minggu ini?\n\n"
        f"Sorotan dari {article['source']} tentang \"{clean_title}\" mengingatkan calon pembeli rumah "
        "untuk menghitung ulang kesiapan finansial sebelum mengambil keputusan KPR tahun ini.\n\n"
        "Tiga langkah aman sebelum ajukan KPR:\n"
        "1. Jaga rasio total cicilan bulanan maksimal 30% dari penghasilan bersih agar arus kas tetap sehat.\n"
        "2. Siapkan dana pra-akad sekitar 8% sampai 12% dari harga rumah untuk BPHTB, notaris, provisi bank, dan asuransi.\n"
        "3. Bandingkan harga pasar rumah seken dan rumah baru di area incaran supaya tidak salah ambil plafon kredit.\n\n"
        "Sebelum survei lokasi, gunakan fitur Simulasi KPR di website atau aplikasi Rumah123 untuk cek "
        "estimasi cicilan bulanan berdasarkan harga properti, DP, suku bunga, dan tenor.\n\n"
        "Kalau bujet sudah siap tahun ini, kamu tim beli rumah seken siap huni atau rumah baru inden? "
        "Save postingan ini dan tulis alasanmu di kolom komentar!\n\n"
        "#Rumah123 #SimulasiKPR #TipsKPR #BeliRumah #PropertiIndonesia"
    )


def generate_caption(article: dict[str, str], offline: bool = False) -> tuple[str, str]:
    if offline:
        return _fallback_caption(article), "offline-template"

    user_prompt = build_user_prompt(article)
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if gemini_key:
            return _call_gemini_rest(SYSTEM_PROMPT, user_prompt, gemini_key), os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

        openai_key = os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("GROQ_API_KEY", "").strip()
        if openai_key:
            base = os.environ.get("OPENAI_BASE_URL", "https://api.groq.com/openai/v1" if os.environ.get("GROQ_API_KEY") else "https://api.openai.com/v1")
            model = os.environ.get("OPENAI_MODEL", "llama-3.3-70b-versatile" if "groq" in base else "gpt-4o-mini")
            return _call_openai_compat(SYSTEM_PROMPT, user_prompt, openai_key, base, model), model

        vault_dir = os.environ.get("LLM_VAULT_DIR", "").strip()
        if vault_dir and os.path.isdir(vault_dir):
            if vault_dir not in sys.path:
                sys.path.insert(0, vault_dir)
            from hub import ask_llm  # type: ignore
            res = ask_llm(
                prompt=user_prompt,
                system_prompt=SYSTEM_PROMPT,
                provider=os.environ.get("LLM_VAULT_PROVIDER", "groq"),
                max_tokens=8192,
                temperature=0.35,
                timeout=20.0,
                return_meta=True,
            )
            return res["text"].strip(), f"{res['provider']}:{res['model']}"
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError, KeyError) as exc:
        print(f"[warn] LLM provider failed ({exc}); using deterministic fallback.", file=sys.stderr)

    return _fallback_caption(article), "offline-template"


def lint_caption(raw_caption: str) -> dict[str, Any]:
    text = raw_caption.replace("**", "").replace("__", "")
    text = text.replace("\u202f", "").replace("\u00a0", " ").replace("\u2011", "-")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[\*\-]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"^(\d+\.)([A-Za-z])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"([a-z])(20\d{2})\b", r"\1 \2", text)
    # Replace em-dash, en-dash, and double-hyphen connectors with commas/colons for natural IG prose.
    text = text.replace("\u2014", ", ").replace("\u2013", "-").replace(" -- ", ", ")
    text = re.sub(r",[ \t]*,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hook_words = len(lines[0].split()) if lines else 0
    hashtags = re.findall(r"#[A-Za-z0-9_]+", text)
    body_without_tags = re.sub(r"#[A-Za-z0-9_]+", "", text).strip()
    word_count = len(body_without_tags.split())
    has_brand = "rumah123" in body_without_tags.lower()
    uses_formal_anda = bool(re.search(r"\banda\b", body_without_tags, flags=re.IGNORECASE))

    issues: list[str] = []
    if hook_words > 16:
        issues.append(f"hook_too_long ({hook_words})")
    if not (95 <= word_count <= 250):
        issues.append(f"word_count_out_of_range ({word_count})")
    if not (3 <= len(hashtags) <= 6):
        issues.append(f"hashtag_count_out_of_range ({len(hashtags)})")
    if not has_brand:
        issues.append("missing_rumah123_mention")
    if uses_formal_anda:
        issues.append("formal_pronoun_anda")

    return {
        "caption": text,
        "passed": len(issues) == 0,
        "metrics": {
            "hook_words": hook_words,
            "word_count": word_count,
            "hashtag_count": len(hashtags),
            "has_rumah123_mention": has_brand,
            "uses_kamu_voice": not uses_formal_anda,
        },
        "issues": issues,
    }


def run_pipeline(top_k: int = 3, offline: bool = False, output_path: str = "sample_outputs.json") -> dict[str, Any]:
    raw_articles: list[dict[str, str]] = []
    if not offline:
        try:
            raw_articles = fetch_rss_articles()
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError) as exc:
            print(f"[warn] RSS fetch failed ({exc}); falling back to fixture.", file=sys.stderr)
    top_articles = rank_and_deduplicate(raw_articles, top_k=top_k) if raw_articles else [
        {
            "title": "Harga Rumah Makin Mahal, Rumah Lelang-Rumah Bekas Jadi Alternatif?",
            "source": "CNBC Indonesia",
            "published_at": "Wed, 04 Nov 2026 04:45:00 GMT",
            "url": "https://news.google.com",
            "snippet": "Harga Rumah Makin Mahal, Rumah Lelang-Rumah Bekas Jadi Alternatif?",
            "relevance_score": 13,
        }
    ]

    posts: list[dict[str, Any]] = []
    for idx, art in enumerate(top_articles, start=1):
        raw_caption, model_used = generate_caption(art, offline=offline)
        gate = lint_caption(raw_caption)
        posts.append({
            "slot": idx,
            "source_article": art,
            "model_used": model_used,
            "status": "READY_FOR_REVIEW" if gate["passed"] else "NEEDS_REVISION",
            "quality_gate": {
                "passed": gate["passed"],
                "metrics": gate["metrics"],
                "issues": gate["issues"],
            },
            "instagram_caption": gate["caption"],
        })

    report = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rss_query": DEFAULT_RSS_QUERY,
        "raw_articles_fetched": len(raw_articles),
        "selected_count": len(posts),
        "posts": posts,
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weekly Indonesian Property News to Rumah123 IG Caption Pipeline")
    parser.add_argument("--top-k", type=int, default=3, help="Number of distinct weekly posts to generate")
    parser.add_argument("--offline", action="store_true", help="Run without live network/LLM calls")
    parser.add_argument("--output", default="sample_outputs.json", help="Output JSON artifact path")
    args = parser.parse_args()

    result = run_pipeline(top_k=args.top_k, offline=args.offline, output_path=args.output)
    print(f"Fetched {result['raw_articles_fetched']} RSS items -> generated {result['selected_count']} captions.")
    for item in result["posts"]:
        print(f"\n[{item['slot']}] {item['source_article']['source']} | {item['source_article']['title']}")
        print(f"Gate: {item['status']} | Metrics: {item['quality_gate']['metrics']}")
        print("-" * 60)
        print(item["instagram_caption"])
