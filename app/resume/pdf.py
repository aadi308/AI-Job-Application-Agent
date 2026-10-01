from playwright.sync_api import sync_playwright


def html_to_pdf(html: str, output_path: str) -> None:
    # Page margins are controlled by @page CSS in the template, not here, to avoid
    # double-margining.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        page.pdf(
            path=output_path,
            format="Letter",
            print_background=True,
            margin={"top": "0in", "bottom": "0in", "left": "0in", "right": "0in"},
        )
        browser.close()
