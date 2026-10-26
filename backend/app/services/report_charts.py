"""科研报告静态图表；全部输入由数据库快照提供。"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib.figure import Figure

FONT_CANDIDATES=(Path("C:/Windows/Fonts/msyh.ttc"),Path("C:/Windows/Fonts/simhei.ttf"),Path("C:/Windows/Fonts/simsun.ttc"))
FONT=font_manager.FontProperties(fname=str(next((p for p in FONT_CANDIDATES if p.exists()),"")))


def _save(figure:Figure,path:Path)->str:
    figure.savefig(path,dpi=180,bbox_inches="tight",facecolor="white");data=path.read_bytes();return base64.b64encode(data).decode()


def line_chart(path:Path,x:list,y_series:list[tuple[str,list]],title:str,ylabel:str)->str:
    figure=Figure(figsize=(8.2,3.8));axis=figure.subplots();colors=("#2f6f9f","#c8763e","#487d56","#8a5a96")
    for index,(label,values) in enumerate(y_series):axis.plot(range(len(x)),values,label=label,color=colors[index%len(colors)],linewidth=1.6)
    axis.set_title(title,fontproperties=FONT,fontsize=13);axis.set_ylabel(ylabel,fontproperties=FONT);axis.grid(True,color="#dfe6eb",linewidth=.6);axis.tick_params(labelsize=8)
    if len(x)>1:
        ticks=sorted(set([0,len(x)//4,len(x)//2,3*len(x)//4,len(x)-1]));axis.set_xticks(ticks,[x[i][:10] for i in ticks],rotation=20)
    if len(y_series)>1:axis.legend(prop=FONT,frameon=False)
    figure.tight_layout();return _save(figure,path)


def track_chart(path:Path,longitude:list[float],latitude:list[float],title:str)->str:
    figure=Figure(figsize=(6.5,5));axis=figure.subplots();axis.plot(longitude,latitude,color="#236c9b",linewidth=1.6,marker="o",markersize=2)
    if longitude:axis.scatter([longitude[0]],[latitude[0]],color="#35804a",label="起点");axis.scatter([longitude[-1]],[latitude[-1]],color="#b34d48",label="终点")
    axis.set_title(title,fontproperties=FONT);axis.set_xlabel("经度 (°)",fontproperties=FONT);axis.set_ylabel("纬度 (°)",fontproperties=FONT);axis.grid(True,color="#dfe6eb",linewidth=.6);axis.legend(prop=FONT,frameon=False);figure.tight_layout();return _save(figure,path)


def bar_chart(path:Path,labels:list[str],values:list[float],title:str,ylabel:str)->str:
    figure=Figure(figsize=(7.5,3.8));axis=figure.subplots();bars=axis.bar(labels,values,color="#397fa5")
    axis.set_title(title,fontproperties=FONT);axis.set_ylabel(ylabel,fontproperties=FONT);axis.grid(axis="y",color="#dfe6eb",linewidth=.6)
    for bar,value in zip(bars,values):axis.text(bar.get_x()+bar.get_width()/2,value,f"{value:.3f}",ha="center",va="bottom",fontsize=8)
    figure.tight_layout();return _save(figure,path)


def histogram(path:Path,values:list[float],title:str)->str:
    figure=Figure(figsize=(7.5,3.8));axis=figure.subplots();axis.hist(values,bins=min(20,max(5,int(len(values)**.5))),color="#4e819c",edgecolor="white")
    axis.axvline(0,color="#9f4d49",linewidth=1);axis.set_title(title,fontproperties=FONT);axis.set_xlabel("残差 (m/s)",fontproperties=FONT);axis.set_ylabel("样本数",fontproperties=FONT);axis.grid(axis="y",color="#dfe6eb",linewidth=.6);figure.tight_layout();return _save(figure,path)
