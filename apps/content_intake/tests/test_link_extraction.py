from apps.content_intake.sheets_sync import _link_type, _extract_cell_links


def test_link_type_classification():
    assert _link_type("https://docs.google.com/document/d/abc/edit") == "gdoc"
    assert _link_type("https://docs.google.com/spreadsheets/d/x") == "gsheet"
    assert _link_type("https://drive.google.com/file/d/y") == "gdrive"
    assert _link_type("https://example.com/report.pdf") == "pdf"
    assert _link_type("https://example.com/page") == "link"


def test_extract_whole_cell_hyperlink():
    cell = {"formattedValue": "Brief Doc", "hyperlink": "https://docs.google.com/document/d/abc/edit"}
    links = _extract_cell_links(cell)
    assert links == [{"title": "Brief Doc", "url": "https://docs.google.com/document/d/abc/edit", "type": "gdoc"}]


def test_extract_drive_chip():
    cell = {
        "formattedValue": "",
        "chipRuns": [
            {"chip": {"richLinkProperties": {"uri": "https://drive.google.com/file/d/xyz", "label": "KALRO data"}}}
        ],
    }
    links = _extract_cell_links(cell)
    assert links == [{"title": "KALRO data", "url": "https://drive.google.com/file/d/xyz", "type": "gdrive"}]


def test_extract_plain_cell_has_no_links():
    assert _extract_cell_links({"formattedValue": "just text"}) == []


def test_extract_falls_back_to_uri_when_no_label():
    cell = {"chipRuns": [{"chip": {"richLinkProperties": {"uri": "https://example.com/x.pdf"}}}]}
    links = _extract_cell_links(cell)
    assert links == [{"title": "https://example.com/x.pdf", "url": "https://example.com/x.pdf", "type": "pdf"}]
