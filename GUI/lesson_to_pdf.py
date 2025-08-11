from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
import os
import json

class LevelTrackingDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        self.level_pages = {}  # map page_num -> level name
        self.current_level = None

    def afterFlowable(self, flowable):
        if hasattr(flowable, 'level_name'):
            self.current_level = flowable.level_name
            self.level_pages[self.page] = self.current_level

    def get_level_for_page(self, page_num):
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
        self.width, self.height = A4

        # Custom color palette
        self.primary_color = colors.HexColor('#2C3E50')  # Dark blue
        self.secondary_color = colors.HexColor('#E74C3C')  # Red
        self.accent_color = colors.HexColor('#3498DB')  # Blue
        self.light_gray = colors.HexColor('#ECF0F1')
        self.dark_gray = colors.HexColor('#7F8C8D')

        # Get default styles
        self.styles = getSampleStyleSheet()

        # Create custom styles without name conflicts
        # Title Page Styles
        self.styles.add(ParagraphStyle(
            name='LingoTitle',
            parent=self.styles['Title'],
            fontSize=28,
            leading=32,
            alignment=TA_CENTER,
            spaceAfter=18,
            textColor=self.primary_color,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='LingoSubtitle',
            parent=self.styles['BodyText'],
            fontSize=16,
            leading=20,
            alignment=TA_CENTER,
            spaceAfter=40,
            textColor=self.dark_gray,
            fontName='Helvetica'
        ))

        # Header Styles
        self.styles.add(ParagraphStyle(
            name='LingoLevelHeading',
            parent=self.styles['Heading1'],
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            spaceAfter=12,
            spaceBefore=12,
            textColor=self.primary_color,
            fontName='Helvetica-Bold',
            borderWidth=1,
            borderColor=self.primary_color,
            borderPadding=(5, 5, 5, 5),
            backColor=self.light_gray
        ))

        self.styles.add(ParagraphStyle(
            name='LingoLessonHeading',
            parent=self.styles['Heading2'],
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            spaceAfter=12,
            spaceBefore=12,
            textColor=self.secondary_color,
            fontName='Helvetica-Bold',
            underlineWidth=1,
            underlineOffset=-4,
            underlineColor=self.secondary_color
        ))

        # Content Styles
        self.styles.add(ParagraphStyle(
            name='LingoHeading2',
            parent=self.styles['Heading2'],
            fontSize=16,
            leading=20,
            alignment=TA_LEFT,
            spaceBefore=12,
            spaceAfter=8,
            textColor=self.primary_color,
            fontName='Helvetica-Bold',
            leftIndent=10
        ))

        self.styles.add(ParagraphStyle(
            name='LingoBodyText',
            parent=self.styles['BodyText'],
            fontSize=12,
            leading=16,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
            textColor=colors.black,
            fontName='Helvetica',
            firstLineIndent=12
        ))

        self.styles.add(ParagraphStyle(
            name='LingoExample',
            parent=self.styles['BodyText'],
            fontSize=11,
            leading=15,
            leftIndent=20,
            spaceAfter=6,
            textColor=self.accent_color,
            fontName='Helvetica',  # Base font name
            italic=True,           # Add italic property separately
            backColor=self.light_gray,
            borderWidth=0.5,
            borderColor=self.accent_color,
            borderPadding=(5, 5, 5, 5)
        ))

        self.styles.add(ParagraphStyle(
            name='LingoVocabulary',
            parent=self.styles['BodyText'],
            fontSize=12,
            leading=16,
            leftIndent=10,
            spaceAfter=4,
            textColor=colors.black,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='LingoFooter',
            parent=self.styles['Normal'],
            fontSize=9,
            alignment=TA_CENTER,
            textColor=self.dark_gray,
            fontName='Helvetica-Oblique'
        ))

        # Table of Contents styles
        self.toc = TableOfContents()
        self.toc.levelStyles = [
            ParagraphStyle(
                name='LingoTOCLevel1',
                parent=self.styles['Heading1'],
                fontSize=14,
                leftIndent=20,
                firstLineIndent=-20,
                spaceBefore=5,
                leading=18,
                textColor=self.primary_color,
                fontName='Helvetica-Bold'
            ),
            ParagraphStyle(
                name='LingoTOCLevel2',
                parent=self.styles['Heading2'],
                fontSize=12,
                leftIndent=40,
                firstLineIndent=-20,
                spaceBefore=3,
                leading=16,
                textColor=self.secondary_color,
                fontName='Helvetica'
            ),
            ParagraphStyle(
                name='LingoTOCLevel3',
                parent=self.styles['Normal'],
                fontSize=11,
                leftIndent=60,
                firstLineIndent=-20,
                spaceBefore=2,
                leading=14,
                textColor=self.dark_gray,
                fontName='Helvetica'
            ),
        ]

    def header_footer(self, canvas, doc):
        canvas.saveState()
        
        # Header
        canvas.setStrokeColor(self.primary_color)
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, self.height - doc.topMargin + 10, 
                   doc.width + doc.leftMargin, self.height - doc.topMargin + 10)
        
        canvas.setFont('Helvetica-Bold', 10)
        canvas.setFillColor(self.primary_color)
        canvas.drawString(doc.leftMargin, self.height - doc.topMargin + 15, 
                         "Lingo - AI Language Learning Textbook")
        
        # Footer
        level = doc.get_level_for_page(doc.page) or "Pre-intermediate Level"
        
        canvas.setStrokeColor(self.primary_color)
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, doc.bottomMargin - 0.5, 
                   doc.width + doc.leftMargin, doc.bottomMargin - 0.5)
        
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(self.dark_gray)
        canvas.drawCentredString(self.width / 2, doc.bottomMargin - 15, level)
        canvas.drawRightString(self.width - doc.rightMargin + 20, doc.bottomMargin - 15, 
                              f"Page {doc.page}")
        
        canvas.restoreState()

    def create_pdf(self):
        doc = LevelTrackingDocTemplate(
            self.output_path,
            pagesize=A4,
            rightMargin=1.5*cm,
            leftMargin=1.5*cm,
            topMargin=1.8*cm,
            bottomMargin=1.8*cm
        )
        
        frame = Frame(
            doc.leftMargin,
            doc.bottomMargin,
            doc.width,
            doc.height - 1.5*cm,
            leftPadding=0,
            rightPadding=0,
            bottomPadding=0,
            topPadding=0,
            id='normal'
        )
        
        template = PageTemplate(id='main_template', frames=frame, onPage=self.header_footer)
        doc.addPageTemplates([template])

        self.story = []

        # Cover page with improved design
        self.story.append(Spacer(1, 3*cm))
        
        # Add a decorative element (you can replace with your logo)
        try:
            logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
            if os.path.exists(logo_path):
                logo = Image(logo_path, width=4*cm, height=4*cm)
                logo.hAlign = 'CENTER'
                self.story.append(logo)
                self.story.append(Spacer(1, 1*cm))
        except:
            pass
        
        self.story.append(Paragraph("Lingo Language Learning Tutor", self.styles['LingoTitle']))
        self.story.append(Paragraph("AI Driven Robotic Head for Language Learning Assistance", self.styles['LingoSubtitle']))
        self.story.append(Paragraph("Textbook for Pre-intermediate and Intermediate Levels", 
                                   self.styles['LingoSubtitle']))
        self.story.append(Spacer(1, 4*cm))
        self.story.append(Paragraph("© 2025 Final Year Thesis (Mechatronic Engineering Department) ", 
                                  ParagraphStyle(name='Copyright', fontSize=10, alignment=TA_CENTER)))
        self.story.append(Paragraph("Yan Naing Kyaw Tint (Software) ", 
                                  ParagraphStyle(name='Copyright', fontSize=10, alignment=TA_CENTER)))
        self.story.append(Paragraph("Ngwe Thant Sin (Hardware) ", 
                                  ParagraphStyle(name='Copyright', fontSize=10, alignment=TA_CENTER)))
        self.story.append(PageBreak())

        # Table of Contents
        toc_title = Paragraph("Table of Contents", self.styles['LingoLevelHeading'])
        toc_title.level_name = "Table of Contents"
        self.story.append(toc_title)
        self.story.append(Spacer(1, 0.5*cm))
        self.story.append(self.toc)
        self.story.append(PageBreak())

        # Process each level folder
        for level_folder, level_name in [('A2 Level (Pre-Intermediate)', 'Pre-intermediate Level'),
                                       ('B1 Level (Intermediate)', 'Intermediate Level')]:
            self.current_level_text = level_name
            level_path = os.path.join(self.lessons_root, level_folder)

            # Level heading with improved design
            level_heading = Paragraph(level_name, self.styles['LingoLevelHeading'])
            level_heading.level_name = level_name
            self.story.append(level_heading)
            self.story.append(Spacer(1, 0.3*cm))

            # Add to TOC
            self.toc.addEntry(0, level_name, doc.page if hasattr(doc, 'page') else 0)

            # Process lesson types
            for lesson_type in ['Grammar', 'Vocabulary', 'Reading']:
                lesson_type_path = os.path.join(level_path, lesson_type)
                if not os.path.isdir(lesson_type_path):
                    continue

                # Lesson type heading with improved design
                lesson_type_heading = Paragraph(lesson_type, self.styles['LingoHeading2'])
                lesson_type_heading._bookmarkName = f"{level_name}_{lesson_type}"
                self.story.append(lesson_type_heading)

                # Add to TOC
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

        doc.build(self.story)

    def add_lesson(self, lesson):
        # Lesson title with improved design
        title = lesson.get('title', 'Untitled Lesson')
        lesson_heading = Paragraph(title, self.styles['LingoLessonHeading'])
        lesson_heading._bookmarkName = title
        self.story.append(lesson_heading)

        summary = lesson.get('summary', '')
        if summary:
            self.story.append(Paragraph(summary, self.styles['LingoBodyText']))

        t = lesson.get('type', '').lower()
        if t == 'vocabulary':
            for section in lesson.get('sections', []):
                self.story.append(Paragraph(section.get('heading', ''), self.styles['LingoHeading2']))
                content = section.get('content', '')
                if content:
                    self.story.append(Paragraph(content, self.styles['LingoBodyText']))
                for example in section.get('examples', []):
                    phrase = example.get('phrase', '')
                    definition = example.get('definition', '')
                    example_text = example.get('example', '')
                    self.story.append(Paragraph(f"<b>{phrase}</b>: {definition}", 
                                             self.styles['LingoVocabulary']))
                    if example_text:
                        self.story.append(Paragraph(f"<i>Example:</i> {example_text}", 
                                                 self.styles['LingoExample']))
                self.story.append(Spacer(1, 0.2*cm))

        elif t == 'reading':
            for passage in lesson.get('passages', []):
                self.story.append(Paragraph(passage.get('title', ''), self.styles['LingoHeading2']))
                self.story.append(Paragraph(passage.get('text', ''), self.styles['LingoBodyText']))
                self.story.append(Spacer(1, 0.2*cm))
            if 'questions' in lesson:
                self.story.append(Paragraph("Comprehension Questions", self.styles['LingoHeading2']))
                for q in lesson['questions']:
                    self.story.append(Paragraph(f"<b>Q{q['id']}:</b> {q['question']}", 
                                             self.styles['LingoBodyText']))
                    if 'options' in q:
                        options = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(q['options'])])
                        self.story.append(Paragraph(options.replace("\n", "<br/>"), 
                                         self.styles['LingoExample']))
                    if 'hint' in q:
                        self.story.append(Paragraph(f"<i>Hint:</i> {q['hint']}", 
                                                 self.styles['LingoExample']))
                    self.story.append(Spacer(1, 0.2*cm))

        elif t == 'grammar':
            for para in lesson.get('content', []):
                self.story.append(Paragraph(para, self.styles['LingoBodyText']))
            self.story.append(Spacer(1, 0.3*cm))
            for ex in lesson.get('examples', []):
                if isinstance(ex, dict):
                    rule = ex.get('rule', '')
                    self.story.append(Paragraph(f"<b>{rule}</b>", self.styles['LingoHeading2']))
                    for example_line in ex.get('examples', []):
                        self.story.append(Paragraph(example_line, self.styles['LingoExample']))
                    self.story.append(Spacer(1, 0.2*cm))
                else:
                    self.story.append(Paragraph(ex, self.styles['LingoExample']))
            tips = lesson.get('tips', [])
            if tips:
                self.story.append(Paragraph("Usage Tips", self.styles['LingoHeading2']))
                for tip in tips:
                    self.story.append(Paragraph(f"• {tip}", self.styles['LingoBodyText']))

        self.story.append(Spacer(1, 0.2*cm))


if __name__ == "__main__":
    lessons_root = "/home/robinglory/Desktop/Thesis/english_lessons"
    output_pdf = "Lingo_Textbook.pdf"
    pdf = PDFTextbook(output_pdf, lessons_root)
    pdf.create_pdf()
    print(f"PDF textbook created at: {output_pdf}")
