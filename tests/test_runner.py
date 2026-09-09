"""The CSV that scrape_site writes: deduplicated by url, ordered, stdlib-only."""
import csv

import runner


def _site(tmp_path, pages):
    """A registry entry whose parser serves `pages` in order, then nothing."""
    served = iter(pages)
    return {
        "name": "fake",
        "base_url": "https://example.test/x",
        "pagination": "page_param",
        "parser": lambda html: next(served, []),
        "output": str(tmp_path / "fake_jdm.csv"),
    }


def _row(title, url, price="$1.000"):
    return {"title": title, "original_price": price, "current_price": "",
            "stock_status": "", "url": url}


def test_dedupes_on_url_not_title(tmp_path, monkeypatch):
    """A store may list one title twice at different urls; both are real."""
    monkeypatch.setattr(runner, "fetch_html", lambda url: "<html/>")
    page = [
        _row("Drunagor", "https://example.test/drunagor-despertar"),
        _row("Drunagor", "https://example.test/drunagor-apocalipsis"),
        _row("Azul", "https://example.test/azul"),
        _row("Azul (again)", "https://example.test/azul"),   # same url: a dupe
    ]
    rows = runner.scrape_site(_site(tmp_path, [page]), dry_run=True)

    assert [r["url"] for r in rows] == [
        "https://example.test/azul",
        "https://example.test/drunagor-apocalipsis",
        "https://example.test/drunagor-despertar",
    ], "sorted by url, one row per url, distinct titles kept"


def test_written_csv_matches_returned_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "fetch_html", lambda url: "<html/>")
    page = [_row("B", "https://example.test/b"), _row("A", "https://example.test/a")]
    rows = runner.scrape_site(_site(tmp_path, [page]), dry_run=True)

    written = list(csv.DictReader((tmp_path / "fake_jdm.csv").open(encoding="utf-8")))
    assert written == rows
    assert list(written[0]) == ["title", "original_price", "current_price",
                                "stock_status", "url"]


def test_empty_scrape_returns_empty_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "fetch_html", lambda url: "<html/>")
    assert runner.scrape_site(_site(tmp_path, [[]]), dry_run=True) == []
    assert not (tmp_path / "fake_jdm.csv").exists()
