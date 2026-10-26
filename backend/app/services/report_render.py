"""将稳定数据快照渲染为独立 HTML 与 A4 中文 PDF。"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle,getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image,PageBreak,Paragraph,SimpleDocTemplate,Spacer,Table,TableStyle


def _font()->str:
    candidates=(Path("C:/Windows/Fonts/msyh.ttc"),Path("C:/Windows/Fonts/simsun.ttc"))
    for path in candidates:
        if path.exists():
            try:pdfmetrics.registerFont(TTFont("ReportCN",str(path),subfontIndex=0));return "ReportCN"
            except Exception:continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"));return "STSong-Light"


def render_html(path:Path,title:str,report_no:str,sections:list[dict],generated_at:str,source_text:str):
    body=[];figure=table=0
    for section in sections:
        body.append(f"<h2>{html.escape(section['title'])}</h2>")
        for paragraph in section.get("paragraphs",[]):body.append(f"<p>{html.escape(str(paragraph))}</p>")
        for image in section.get("images",[]):
            figure+=1;body.append(f"<figure><img src=\"data:image/png;base64,{image['data']}\"><figcaption>图 {figure}　{html.escape(image['caption'])}</figcaption></figure>")
        if section.get("table"):
            table+=1;headers,rows=section["table"];body.append(f"<div class=\"caption\">表 {table}　{html.escape(section.get('table_caption','数据表'))}</div><table><thead><tr>"+"".join(f"<th>{html.escape(str(x))}</th>" for x in headers)+"</tr></thead><tbody>")
            body.extend("<tr>"+"".join(f"<td>{html.escape('' if x is None else str(x))}</td>" for x in row)+"</tr>" for row in rows);body.append("</tbody></table>")
    document=f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title><style>
@page{{size:A4;margin:22mm 18mm 20mm}}*{{box-sizing:border-box}}body{{max-width:174mm;margin:0 auto;color:#1e2933;background:white;font:14px/1.75 'Microsoft YaHei','SimSun',sans-serif}}header{{border-bottom:2px solid #476b82;padding:18px 0 12px;margin-bottom:24px}}h1{{font-size:25px;text-align:center;margin:8px 0}}h2{{font-size:18px;color:#294f68;border-bottom:1px solid #cbd6dd;padding-bottom:5px;margin-top:26px}}.meta{{font-size:12px;color:#596b77;text-align:center}}p{{text-align:justify}}figure{{margin:18px 0;page-break-inside:avoid}}img{{display:block;max-width:100%;max-height:118mm;margin:auto}}figcaption,.caption{{text-align:center;font-size:12px;color:#4e5e68;margin:7px 0}}table{{width:100%;border-collapse:collapse;font-size:11px;page-break-inside:auto}}th,td{{border:1px solid #aebbc4;padding:5px 7px;text-align:left;overflow-wrap:anywhere}}th{{background:#eaf0f4}}tr{{page-break-inside:avoid}}footer{{margin-top:28px;border-top:1px solid #cbd6dd;padding-top:8px;font-size:11px;color:#657681}}code{{font-family:Consolas,monospace}}
</style></head><body><header><div class=\"meta\">云浪智析 · 科研分析报告　|　编号 {html.escape(report_no)}</div><h1>{html.escape(title)}</h1><div class=\"meta\">生成时间：{html.escape(generated_at)}　|　{html.escape(source_text)}</div></header>{''.join(body)}<footer>本报告由真实数据库快照生成，仅供科研教学，不构成业务气象预报或预警。</footer></body></html>"""
    path.write_text(document,encoding="utf-8")


class NumberedDocTemplate(SimpleDocTemplate):
    def afterPage(self):pass


def render_pdf(path:Path,title:str,report_no:str,sections:list[dict],generated_at:str,source_text:str):
    font=_font();styles=getSampleStyleSheet();normal=ParagraphStyle("CN",parent=styles["BodyText"],fontName=font,fontSize=10.5,leading=17,spaceAfter=7);heading=ParagraphStyle("CNH",parent=styles["Heading2"],fontName=font,fontSize=15,leading=22,textColor=colors.HexColor("#294f68"),spaceBefore=12,spaceAfter=8);title_style=ParagraphStyle("CNT",parent=styles["Title"],fontName=font,fontSize=21,leading=29,alignment=TA_CENTER,textColor=colors.HexColor("#1f3f53"))
    def page(canvas,doc):
        canvas.saveState();canvas.setFont(font,8);canvas.setFillColor(colors.HexColor("#657681"));canvas.drawString(18*mm,12*mm,f"云浪智析 · {report_no}");canvas.drawRightString(192*mm,12*mm,f"第 {doc.page} 页");canvas.restoreState()
    doc=NumberedDocTemplate(str(path),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=20*mm,title=title,author="云浪智析")
    story=[Paragraph(html.escape(title),title_style),Spacer(1,5*mm),Paragraph(html.escape(f"报告编号：{report_no}"),normal),Paragraph(html.escape(f"生成时间：{generated_at}"),normal),Paragraph(html.escape(source_text),normal),Spacer(1,4*mm)]
    figure=table_no=0
    for section in sections:
        story.append(Paragraph(html.escape(section["title"]),heading))
        story.extend(Paragraph(html.escape(str(p)),normal) for p in section.get("paragraphs",[]))
        for image in section.get("images",[]):
            figure+=1;story.extend([Image(image["path"],width=165*mm,height=min(92*mm,165*mm*image.get("ratio",.48))),Paragraph(html.escape(f"图 {figure}　{image['caption']}"),ParagraphStyle("cap",parent=normal,alignment=TA_CENTER,fontSize=9))])
        if section.get("table"):
            table_no+=1;headers,rows=section["table"];data=[[Paragraph(html.escape(str(x)),normal) for x in headers]]+[[Paragraph(html.escape("" if x is None else str(x)),normal) for x in row] for row in rows]
            widths=[165*mm/len(headers)]*len(headers);table=Table(data,colWidths=widths,repeatRows=1,hAlign="LEFT")
            table.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,-1),8),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eaf0f4")),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#9aaab4")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]));story.extend([Paragraph(html.escape(f"表 {table_no}　{section.get('table_caption','数据表')}"),ParagraphStyle("cap2",parent=normal,alignment=TA_CENTER,fontSize=9)),table])
    doc.build(story,onFirstPage=page,onLaterPages=page)
