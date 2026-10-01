from jinja2 import Template

from app.resume.models import StructuredResume

# Styled to match the candidate's real original resume (centered navy-blue name, navy
# section headers with an underline, centered contact line) rather than a generic
# template — while keeping every ATS-safety constraint from the original version: no
# tables, no images/icons, no headers/footers, no multi-column layout, no text boxes,
# standard system fonts only. Color and layout choices here are purely CSS on plain
# text/divs, so they don't affect text extraction (verified by pdf_validate.py).
_TEMPLATE = Template(
    """
<html>
<head>
<meta charset="utf-8">
<style>
  @page { size: Letter; margin: 0.55in; }
  body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 10.5pt;
    line-height: 1.35;
    color: #1a1a1a;
    margin: 0;
  }
  .header { text-align: center; margin-bottom: 10pt; }
  h1 {
    font-size: 19pt;
    letter-spacing: 0.02em;
    color: #1a4d8f;
    margin: 0 0 3pt 0;
  }
  .contact {
    font-size: 9.5pt;
    color: #333;
  }
  .contact a { color: #1a4d8f; text-decoration: none; }
  h2 {
    font-size: 11pt;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #1a4d8f;
    border-bottom: 1.25pt solid #1a4d8f;
    margin: 13pt 0 6pt 0;
    padding-bottom: 2pt;
  }
  .summary { margin: 0 0 4pt 0; }
  .skills { margin: 0; }
  .entry { margin-bottom: 8pt; }
  .entry-head { font-weight: bold; }
  .entry-sub { font-style: italic; color: #333; font-size: 10pt; }
  ul { margin: 3pt 0 0 0; padding-left: 16pt; }
  li { margin-bottom: 2pt; }
</style>
</head>
<body>
  <div class="header">
    <h1>{{ resume.header.full_name | upper }}</h1>
    <div class="contact">
      {{ [resume.header.email, resume.header.phone, resume.header.location,
          resume.header.linkedin, resume.header.github, resume.header.portfolio]
         | select | join(' &middot; ') }}
    </div>
  </div>

  <h2>Summary</h2>
  <p class="summary">{{ resume.summary }}</p>

  <h2>Skills</h2>
  <p class="skills">{{ resume.skills | join(', ') }}</p>

  <h2>Experience</h2>
  {% for job in resume.experience %}
  <div class="entry">
    <div class="entry-head">{{ job.title }} — {{ job.company }}</div>
    <div class="entry-sub">{{ job.dates }}</div>
    <ul>
      {% for bullet in job.bullets %}
      <li>{{ bullet.text }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endfor %}

  {% if resume.projects %}
  <h2>Projects</h2>
  {% for project in resume.projects %}
  <div class="entry">
    <div class="entry-head">{{ project.name }}{% if project.tech_stack %} — {{ project.tech_stack | join(', ') }}{% endif %}</div>
    <div>{{ project.description }}</div>
  </div>
  {% endfor %}
  {% endif %}

  <h2>Education</h2>
  {% for edu in resume.education %}
  <div class="entry">
    <div class="entry-head">{{ edu.degree }} — {{ edu.institution }}</div>
    <div class="entry-sub">{{ edu.dates }}</div>
  </div>
  {% endfor %}

  {% if resume.certifications %}
  <h2>Certifications</h2>
  <ul>
    {% for cert in resume.certifications %}
    <li>{{ cert.name }}{% if cert.issuer %} — {{ cert.issuer }}{% endif %}</li>
    {% endfor %}
  </ul>
  {% endif %}
</body>
</html>
"""
)


def render_html(resume: StructuredResume) -> str:
    return _TEMPLATE.render(resume=resume)
