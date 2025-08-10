from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.units import cm
import os
import json

class LevelTrackingDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        self.level_pages = {}  # map page_num -> level name
        self.current_level = None

    def afterFlowable(self, flowable):
        # Detect level headings by custom attribute and record page number
        if hasattr(flowable, 'level_name'):
            self.current_level = flowable.level_name
            self.level_pages[self.page] = self.current_level

    def get_level_for_page(self, page_num):
        # Find the most recent level before or equal to page_num
        keys = sorted(self.level_pages.keys())
        level = None
        for k in keys:
            if page_num >= k:
                level = self.level_pages[k]
            else:
                break
        return level

class PDFTextbook:
    def __init__(self, output_path, lessons_root):
        self.output_path = output_path
        self.lessons_root = lessons_root
        self.styles = getSampleStyleSheet()
        self.width, self.height = A4

        # Custom styles
        self.styles.add(ParagraphStyle(name='TitleCenter', fontSize=24, leading=28, alignment=TA_CENTER, spaceAfter=24, spaceBefore=12))
        self.styles.add(ParagraphStyle(name='LevelHeading', fontSize=22, leading=26, alignment=TA_CENTER, spaceAfter=20, spaceBefore=20, fontName='Helvetica-Bold'))
        self.styles.add(ParagraphStyle(name='LessonHeading', fontSize=20, leading=24, alignment=TA_CENTER, spaceAfter=15, spaceBefore=15, fontName='Helvetica-Bold'))
        self.styles.add(ParagraphStyle(name='MyHeading2Center', fontSize=16, leading=20, alignment=TA_CENTER, spaceBefore=12, spaceAfter=10, fontName='Helvetica-Bold'))
        self.styles.add(ParagraphStyle(name='MyJustify', alignment=TA_JUSTIFY, spaceAfter=10, fontSize=11, leading=15))
        self.styles.add(ParagraphStyle(name='MyExample', fontSize=10, leading=13, leftIndent=20, spaceAfter=6, textColor='darkblue'))
        self.styles.add(ParagraphStyle(name='MyFooter', fontSize=8, alignment=TA_CENTER, textColor='grey'))

        self.current_level_text = ""  # for footer display

        # Table of Contents setup
        self.toc = TableOfContents()
        self.toc.levelStyles = [
            ParagraphStyle(fontSize=14, name='TOCLevel1', leftIndent=20, firstLineIndent=-20, spaceBefore=5, leading=16),
            ParagraphStyle(fontSize=12, name='TOCLevel2', leftIndent=40, firstLineIndent=-20, spaceBefore=0, leading=12),
            ParagraphStyle(fontSize=10, name='TOCLevel3', leftIndent=60, firstLineIndent=-20, spaceBefore=0, leading=10),
        ]

    def header_footer(self, canvas, doc):
        canvas.saveState()
        # Header (draw higher to reduce gap)
        canvas.setFont('Helvetica-Bold', 12)
        canvas.drawString(cm, self.height - 2.5*cm, "Lingo (AI Driven Robotic Head for Language Learning Assistance)")

        # Footer with correct level text for current page
        level = doc.get_level_for_page(doc.page)
        if level is None:
            level = "Pre-intermediate Level"  # fallback default

        canvas.setFont('Helvetica-Oblique', 12)
        canvas.drawCentredString(self.width / 2, cm / 2, level)
        canvas.drawRightString(self.width - cm, cm / 2, f"Page {doc.page}")

        canvas.restoreState()

    def create_pdf(self):
        doc = LevelTrackingDocTemplate(self.output_path, pagesize=A4,
                                      rightMargin=2*cm, leftMargin=2*cm,
                                      topMargin=2*cm, bottomMargin=2*cm)
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height-2*cm, id='normal')
        template = PageTemplate(id='main_template', frames=frame, onPage=self.header_footer)
        doc.addPageTemplates([template])

        self.story = []

        # Cover page with smaller spacer
        self.story.append(Spacer(1, 2*cm))
        self.story.append(Paragraph("Lingo (AI Driven Robotic Head for Language Learning Assistance)", self.styles['TitleCenter']))
        self.story.append(Paragraph("Textbook for Pre-intermediate Level and Intermediate Level", self.styles['TitleCenter']))
        self.story.append(PageBreak())

        # Table of Contents title and TOC placeholder (can be removed later for real TOC)
        self.story.append(Paragraph("Table of Contents", self.styles['LevelHeading']))
        self.story.append(self.toc)
        self.story.append(PageBreak())

        # Process each level folder (A2, B1)
        for level_folder, level_name in [('A2 Level (Pre-Intermediate)', 'Pre-intermediate Level'),
                                         ('B1 Level (Intermediate)', 'Intermediate Level')]:
            self.current_level_text = level_name
            level_path = os.path.join(self.lessons_root, level_folder)

            # Level heading with attribute for tracking
            level_heading = Paragraph(level_name, self.styles['LevelHeading'])
            level_heading.level_name = level_name
            self.story.append(level_heading)
            self.story.append(Spacer(1, 0.5*cm))

            # Inform TOC about level heading
            self.toc.addEntry(0, level_name, doc.page if hasattr(doc, 'page') else 0)

            # Process lesson types inside level folder
            for lesson_type in ['Grammar', 'Vocabulary', 'Reading']:
                lesson_type_path = os.path.join(level_path, lesson_type)
                if not os.path.isdir(lesson_type_path):
                    continue

                # Lesson type heading centered bold
                lesson_type_heading = Paragraph(lesson_type, self.styles['MyHeading2Center'])
                lesson_type_heading._bookmarkName = f"{level_name}_{lesson_type}"
                self.story.append(lesson_type_heading)

                # Inform TOC about lesson type heading
                self.toc.addEntry(1, lesson_type, doc.page if hasattr(doc, 'page') else 0)

                for filename in sorted(os.listdir(lesson_type_path)):
                    if not filename.endswith('.json'):
                        continue
                    filepath = os.path.join(lesson_type_path, filename)
                    print(f"Loading: {filepath}")
                    with open(filepath, 'r', encoding='utf-8') as f:
                        lesson = json.load(f)
                    self.add_lesson(lesson)
                    self.story.append(PageBreak())

        # Build the PDF document
        doc.build(self.story)

    def add_lesson(self, lesson):
        # Big centered lesson title
        title = lesson.get('title', 'Untitled Lesson')
        lesson_heading = Paragraph(title, self.styles['LessonHeading'])
        lesson_heading._bookmarkName = title
        self.story.append(lesson_heading)

        summary = lesson.get('summary', '')
        if summary:
            self.story.append(Paragraph(summary, self.styles['MyJustify']))

        t = lesson.get('type', '').lower()
        if t == 'vocabulary':
            for section in lesson.get('sections', []):
                self.story.append(Paragraph(section.get('heading', ''), self.styles['MyHeading2Center']))
                content = section.get('content', '')
                if content:
                    self.story.append(Paragraph(content, self.styles['MyJustify']))
                for example in section.get('examples', []):
                    phrase = example.get('phrase', '')
                    definition = example.get('definition', '')
                    example_text = example.get('example', '')
                    self.story.append(Paragraph(f"<b>{phrase}</b>: {definition}", self.styles['MyExample']))
                    if example_text:
                        self.story.append(Paragraph(f"Example: {example_text}", self.styles['MyJustify']))
                self.story.append(Spacer(1, 0.3*cm))

        elif t == 'reading':
            for passage in lesson.get('passages', []):
                self.story.append(Paragraph(passage.get('title', ''), self.styles['MyHeading2Center']))
                self.story.append(Paragraph(passage.get('text', ''), self.styles['MyJustify']))
                self.story.append(Spacer(1, 0.2*cm))
            if 'questions' in lesson:
                self.story.append(Paragraph("Questions", self.styles['MyHeading2Center']))
                for q in lesson['questions']:
                    self.story.append(Paragraph(f"Q{q['id']}: {q['question']}", self.styles['MyJustify']))
                    if 'options' in q:
                        options = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(q['options'])])
                        self.story.append(Paragraph(options.replace("\n", "<br/>"), self.styles['MyJustify']))
                    if 'hint' in q:
                        self.story.append(Paragraph(f"Hint: {q['hint']}", self.styles['MyJustify']))
                    self.story.append(Spacer(1, 0.2*cm))

        elif t == 'grammar':
            for para in lesson.get('content', []):
                self.story.append(Paragraph(para, self.styles['MyJustify']))
            self.story.append(Spacer(1, 0.3*cm))
            for ex in lesson.get('examples', []):
                if isinstance(ex, dict):
                    rule = ex.get('rule', '')
                    self.story.append(Paragraph(f"<b>{rule}</b>", self.styles['MyExample']))
                    for example_line in ex.get('examples', []):
                        self.story.append(Paragraph(example_line, self.styles['MyJustify']))
                    self.story.append(Spacer(1, 0.2*cm))
                else:  # Just string example
                    self.story.append(Paragraph(ex, self.styles['MyExample']))
            tips = lesson.get('tips', [])
            if tips:
                self.story.append(Paragraph("Tips", self.styles['MyHeading2Center']))
                for tip in tips:
                    self.story.append(Paragraph(f"• {tip}", self.styles['MyJustify']))

        self.story.append(Spacer(1, 0.2*cm))


if __name__ == "__main__":
    lessons_root = "/home/robinglory/Desktop/Thesis/english_lessons"
    output_pdf = "Lingo_Textbook.pdf"
    pdf = PDFTextbook(output_pdf, lessons_root)
    pdf.create_pdf()
    print(f"PDF textbook created at: {output_pdf}")
