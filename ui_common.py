"""Shared blue-and-white desktop theme, navigation and file-list controls."""
import math
import tkinter as tk
from tkinter import ttk

BG, WHITE, INK, MUTED, BLUE = '#F3F7FE', '#FFFFFF', '#132344', '#627798', '#176FFF'
FIELD = '#F1F6FD'


def icon(root, name, color=BLUE, size=24):
    root = root.winfo_toplevel()
    cache = getattr(root, '_ui_icons', {})
    key = (name,color,size)
    if key in cache: return cache[key]
    paths = {
        'folder': [[(3,8),(12,8),(15,11),(28,11),(25,26),(4,26),(3,8)],[(4,8),(4,5),(13,5),(16,8),(25,8),(25,11)]],
        'file': [[(7,3),(19,3),(26,10),(26,29),(7,29),(7,3)],[(19,3),(19,10),(26,10)],[(11,17),(21,17)],[(11,22),(21,22)]],
        'help': [[(16+12*math.cos(t*math.pi/16),16+12*math.sin(t*math.pi/16)) for t in range(33)],[(12,11),(13,8),(18,8),(21,11),(20,14),(16,17),(16,20)],[(16,24),(16,24.3)]],
        'add': [[(7,3),(19,3),(25,9),(25,15)],[(7,3),(7,28),(15,28)],[(19,3),(19,10),(25,10)],[(23,18),(23,29)],[(18,23),(28,23)]],
        'open': [[(13,6),(6,6),(6,26),(26,26),(26,19)],[(18,4),(28,4),(28,14)],[(28,4),(15,17)]],
        'trash': [[(6,8),(26,8)],[(10,8),(11,28),(23,28),(24,8)],[(12,8),(12,4),(21,4),(21,8)],[(15,13),(15,23)],[(20,13),(20,23)]],
        'bolt': [[(18,3),(9,18),(16,18),(13,29),(24,13),(17,13),(18,3)]],
    }
    image = tk.PhotoImage(master=root,width=size,height=size)
    segments=[(a,b) for path in paths.get(name, paths['file']) for a,b in zip(path,path[1:])]
    for y in range(size):
        for x in range(size):
            px,py=(x+.5)*32/size,(y+.5)*32/size
            for (ax,ay),(bx,by) in segments:
                t=max(0,min(1,((px-ax)*(bx-ax)+(py-ay)*(by-ay))/max(.01,(bx-ax)**2+(by-ay)**2)))
                if (px-ax-t*(bx-ax))**2+(py-ay-t*(by-ay))**2 < 1.15**2:
                    image.put(color,(x,y)); break
    cache[key]=image; root._ui_icons=cache
    return image


def install_tick_indicator(root, style):
    size = max(20, round(float(root.tk.call('tk', 'scaling')) * 13))
    images=[]
    for selected,disabled in ((False,False),(True,False),(False,True),(True,True)):
        image=tk.PhotoImage(master=root,width=size+10,height=size)
        fill='#B6CBEA' if selected and disabled else BLUE if selected else '#E5EBF4'
        for y in range(size):
            for x in range(size):
                if (x<3 or x>=size-3) and (y<3 or y>=size-3):
                    cx=3 if x<3 else size-4; cy=3 if y<3 else size-4
                    if (x-cx)**2+(y-cy)**2>10: continue
                color=fill
                if selected:
                    px,py=x/size,y/size
                    points=((.22,.49),(.42,.69),(.78,.29))
                    for (ax,ay),(bx,by) in zip(points,points[1:]):
                        t=max(0,min(1,((px-ax)*(bx-ax)+(py-ay)*(by-ay))/((bx-ax)**2+(by-ay)**2)))
                        if (px-ax-t*(bx-ax))**2+(py-ay-t*(by-ay))**2 < .06**2: color=WHITE
                image.put(color,(x,y))
        images.append(image)
    root._tick_images=images
    style.element_create('Tick.indicator','image',images[0],('disabled','selected',images[3]),('disabled',images[2]),('selected',images[1]))
    style.layout('TCheckbutton',[('Checkbutton.padding',{'sticky':'nswe','children':[
        ('Tick.indicator',{'side':'left','sticky':''}),('Checkbutton.label',{'side':'left','sticky':'w'})]})])


def configure_style(root):
    root.configure(background=BG)
    style=ttk.Style(root); style.theme_use('clam')
    style.configure('.',font=('Microsoft YaHei UI',11),foreground=INK)
    for name,color in [('TFrame',BG),('Card.TFrame',WHITE),('Inner.TFrame',WHITE),('Soft.TFrame',FIELD)]:
        style.configure(name,background=color,relief='flat',borderwidth=0)
    for name,bg,fg,size,bold in [('TLabel',BG,INK,11,False),('Card.TLabel',WHITE,INK,11,False),
        ('Title.TLabel',WHITE,INK,22,True),('Section.TLabel',WHITE,INK,14,True),
        ('Hint.TLabel',BG,MUTED,10,False),('CardHint.TLabel',WHITE,MUTED,10,False),
        ('Soft.TLabel',FIELD,INK,11,False),('SoftHint.TLabel',FIELD,MUTED,10,False),
        ('SoftTitle.TLabel',FIELD,INK,13,True),('Brand.TLabel',BG,INK,15,True)]:
        style.configure(name,background=bg,foreground=fg,font=('Microsoft YaHei UI',size,'bold' if bold else 'normal'))
    for name,bg,fg,padding in [('TButton',FIELD,BLUE,(14,10)),('Primary.TButton',BLUE,WHITE,(16,12)),
        ('Large.TButton',BLUE,WHITE,(18,17)),('Quiet.TButton',WHITE,INK,(4,10)),
        ('Nav.TButton',BG,'#4B6081',(16,18)),('NavActive.TButton','#DFECFF',BLUE,(16,18))]:
        style.configure(name,background=bg,foreground=fg,bordercolor=bg,lightcolor=bg,darkcolor=bg,
            borderwidth=0,relief='flat',padding=padding,focusthickness=0,focuscolor='#8BB6FF',
            font=('Microsoft YaHei UI',12 if name in ('Large.TButton','Nav.TButton','NavActive.TButton') else 11,
                  'bold' if name in ('Primary.TButton','Large.TButton','NavActive.TButton') else 'normal'),anchor='w' if name.startswith('Nav') else 'center')
        hover='#0B60E8' if bg==BLUE else '#E7F0FF'
        style.map(name,background=[('disabled','#F0F3F8'),('active',hover)],foreground=[('disabled','#A1ADBE')],
            bordercolor=[('active',hover),('!active',bg)],relief=[('pressed','flat'),('!pressed','flat')])
    style.configure('TEntry',padding=(9,9),borderwidth=0,relief='flat',fieldbackground=FIELD,bordercolor=FIELD,lightcolor=FIELD,darkcolor=FIELD)
    style.map('TEntry',bordercolor=[('focus',FIELD),('!focus',FIELD)])
    style.configure('TCombobox',padding=(9,8),borderwidth=0,relief='flat',background=FIELD,fieldbackground=FIELD,bordercolor=FIELD,lightcolor=FIELD,darkcolor=FIELD,arrowsize=13)
    style.map('TCombobox',fieldbackground=[('readonly',FIELD)],foreground=[('readonly',INK)],bordercolor=[('focus',FIELD),('!focus',FIELD)])
    style.configure('TCheckbutton',background=WHITE,padding=(0,7),font=('Microsoft YaHei UI',11))
    style.map('TCheckbutton',background=[('active',WHITE)])
    install_tick_indicator(root,style)
    style.configure('TNotebook',background=BG,borderwidth=0,bordercolor=BG,lightcolor=BG,darkcolor=BG)
    style.layout('Sidebar.TNotebook.Tab',[])
    style.configure('Sidebar.TNotebook',background=BG,borderwidth=0,bordercolor=BG,lightcolor=BG,darkcolor=BG,tabmargins=0)
    style.configure('Settings.TNotebook',background=WHITE,borderwidth=0)
    style.configure('Settings.TNotebook.Tab',background=WHITE,padding=(18,9),font=('Microsoft YaHei UI',11))
    style.map('Settings.TNotebook.Tab',background=[('selected',FIELD)],foreground=[('selected',BLUE)])
    style.configure('Horizontal.TProgressbar',background=BLUE,troughcolor=FIELD,borderwidth=0,thickness=3)
    style.configure('TScrollbar',background='#DCE5F2',troughcolor=WHITE,borderwidth=0,arrowsize=10)
    return style


def card(parent, **kwargs): return ttk.Frame(parent,style='Card.TFrame',padding=22,**kwargs)
def inner(parent, **kwargs): return ttk.Frame(parent,style='Inner.TFrame',**kwargs)


def file_table(parent, columns, labels, widths, *, multiple=False):
    from ui_table import FileTable
    frame=inner(parent); frame.columnconfigure(0,weight=1); frame.rowconfigure(0,weight=1)
    tree=FileTable(frame,columns,labels,widths,multiple=multiple); tree.grid(row=0,column=0,sticky='nsew')
    y=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
    x=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
    def vertical(first,last):
        y.set(first,last)
        if float(first)<=0 and float(last)>=1: y.grid_remove()
        else: y.grid(row=0,column=1,sticky='ns')
    def horizontal(first,last):
        x.set(first,last)
        if float(first)<=0 and float(last)>=1: x.grid_remove()
        else: x.grid(row=1,column=0,sticky='ew')
    tree.configure(yscrollcommand=vertical,xscrollcommand=horizontal)
    return frame,tree


def wrap_label(parent, variable):
    label=ttk.Label(parent,textvariable=variable,style='CardHint.TLabel',wraplength=800)
    parent.bind('<Configure>',lambda e: label.configure(wraplength=max(200,e.width-44)),add='+')
    def update_visibility(*_):
        if variable.get(): label.grid()
        else: label.grid_remove()
    variable.trace_add('write',update_visibility); label.after_idle(update_visibility)
    return label


class SettingsPanel(ttk.Frame):
    """Scrollable settings above pinned primary actions."""
    def __init__(self,parent,title):
        super().__init__(parent,style='Card.TFrame',padding=(22,24,22,22),width=330)
        self.columnconfigure(0,weight=1); self.rowconfigure(1,weight=1)
        ttk.Label(self,text=title,style='Section.TLabel',font=('Microsoft YaHei UI',18,'bold')).grid(row=0,column=0,sticky='w',pady=(0,20))
        self.canvas=tk.Canvas(self,background=WHITE,borderwidth=0,highlightthickness=0,width=285,height=350)
        self.canvas.grid(row=1,column=0,sticky='nsew')
        self.content=inner(self.canvas); self.content.columnconfigure(0,weight=1)
        self._window=self.canvas.create_window(0,0,anchor='nw',window=self.content)
        scrollbar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        def scroll_state(a,b):
            scrollbar.set(a,b)
            if float(a)<=0 and float(b)>=1: scrollbar.grid_remove()
            else: scrollbar.grid(row=1,column=1,sticky='ns')
        self.canvas.configure(yscrollcommand=scroll_state)
        self.content.bind('<Configure>',lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e: self.canvas.itemconfigure(self._window,width=e.width))
        def wheel(event):
            widget=event.widget
            while widget is not None:
                if widget==self:
                    if self.canvas.yview()!=(0.0,1.0): self.canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
                    return
                widget=getattr(widget,'master',None)
        self.bind_all('<MouseWheel>',wheel,add='+')
        self.actions=inner(self); self.actions.grid(row=2,column=0,sticky='ew',pady=(20,0))


def separator(parent,row):
    tk.Frame(parent,background='#EAF0F8',height=1).grid(row=row,column=0,sticky='ew',pady=20)


def responsive_drop(drop, buttons, subtitle):
    """Keep both import actions reachable when the file panel gets narrower."""
    def reflow(event):
        stacked = event.width < 700
        buttons.grid_configure(row=2 if stacked else 0, column=0 if stacked else 2,
            columnspan=3 if stacked else 1, rowspan=1 if stacked else 2,
            sticky='w', padx=0 if stacked else (12,0), pady=(14,0) if stacked else 0)
        subtitle.configure(wraplength=max(170,event.width-105-(0 if stacked else buttons.winfo_reqwidth())))
    drop.bind('<Configure>',reflow,add='+')
    drop.reflow = reflow


def summary_bar(parent, owner, row):
    area=ttk.Frame(parent,style='Soft.TFrame',padding=(16,15))
    area.grid(row=row,column=0,sticky='ew',pady=(16,0)); area.columnconfigure(0,weight=1)
    owner.status=tk.StringVar(value='就绪 · 提取成功率 —')
    shown=tk.StringVar()
    def change(*_):
        value=owner.status.get().replace(' · 提取成功率','\n提取成功率')
        shown.set(value)
    owner.status.trace_add('write',change); change()
    label=ttk.Label(area,textvariable=shown,style='Soft.TLabel',wraplength=400,justify='left')
    label.grid(row=0,column=0,sticky='w')
    area.bind('<Configure>',lambda e: label.configure(wraplength=max(190,e.width-225)),add='+')
    owner.failed_folder_button=ttk.Button(area,text='打开失败文件夹',image=icon(parent,'folder',size=19),compound='left',command=owner.open_failed_folder,state='disabled')
    owner.failed_folder_button.grid(row=0,column=1,sticky='e',padx=(12,0))
    return area
