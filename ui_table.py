"""Virtual file list with real multi-selection, checkboxes and status badges."""
import tkinter as tk
from tkinter import font as tkfont


class FileTable(tk.Canvas):
    """Small Treeview-compatible surface used by the two file controllers.

    Only visible rows are painted; identifiers and original value order never
    change when selecting, scrolling or resizing the view.
    """
    def __init__(self, parent, columns, labels, widths, multiple=True):
        super().__init__(parent, background='white', highlightthickness=0,
                         borderwidth=0, takefocus=True, width=600, height=330)
        self.columns, self.labels, self.widths = tuple(columns), labels, widths
        self.multiple = multiple
        self._rows, self._selected = {}, set()
        self._focus, self._anchor = '', ''
        self._top, self._left, self._pending = 0, 0, None
        self._yscroll = self._xscroll = None
        self._font = tkfont.Font(self, family='Microsoft YaHei UI', size=11)
        self._heading_font = tkfont.Font(self, family='Microsoft YaHei UI', size=10)
        self.row_height = max(48, self._font.metrics('linespace')+20)
        self.header_height = self.row_height
        self.check_width = 42
        self._positions = []
        self.bind('<Configure>', lambda _: self._schedule())
        self.bind('<Button-1>', self._click)
        self.bind('<MouseWheel>', self._wheel)
        for key in ('Up', 'Down', 'Home', 'End', 'Prior', 'Next', 'space'):
            self.bind('<'+key+'>', self._key)
        self.bind('<Control-a>', self._select_all)
        self.bind('<Control-A>', self._select_all)
        self.bind('<FocusIn>', lambda _: self._schedule())
        self.bind('<FocusOut>', lambda _: self._schedule())

    def configure(self, cnf=None, **kwargs):
        for name in ('yscrollcommand', 'xscrollcommand'):
            if name in kwargs: setattr(self, '_'+name[:1]+'scroll', kwargs.pop(name))
        return super().configure(cnf, **kwargs)

    config = configure

    def _schedule(self):
        if self._pending is None: self._pending = self.after_idle(self._draw)

    def _fit(self, text, width, font=None):
        font = font or self._font; text = str(text)
        if font.measure(text) <= width: return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo+hi+1)//2
            if font.measure(text[:mid]+'…') <= width: lo = mid
            else: hi = mid-1
        return text[:lo]+'…' if width > font.measure('…') else ''

    def _layout(self):
        width = max(1, self.winfo_width())
        sizes = list(self.widths)
        sizes[0] = max(230, width-self.check_width-sum(sizes[1:]))
        self._total_width = self.check_width+sum(sizes)
        self._left = min(self._left, max(0, self._total_width-width))
        x = self.check_width-self._left; self._positions = []
        for size in sizes:
            self._positions.append((x, size)); x += size
        self._page = max(1, (self.winfo_height()-self.header_height)//self.row_height)
        self._top = max(0, min(self._top, max(0, len(self._rows)-self._page)))

    def _round(self, x1, y1, x2, y2, color, radius=9):
        self.create_polygon(x1+radius,y1,x2-radius,y1,x2,y1,x2,y1+radius,
            x2,y2-radius,x2,y2,x2-radius,y2,x1+radius,y2,x1,y2,x1,y2-radius,
            x1,y1+radius,x1,y1, smooth=True, splinesteps=12, fill=color, outline='')

    def _check(self, x, y, selected=False, partial=False):
        size = 19
        self._round(x,y,x+size,y+size,'#1772FF' if selected or partial else '#EDF1F7',3)
        if selected:
            self.create_line(x+4,y+10,x+8,y+14,x+15,y+5,fill='white',width=2.3,
                             capstyle='round',joinstyle='round')
        elif partial: self.create_line(x+5,y+9,x+14,y+9,fill='white',width=2)
        else: self.create_rectangle(x+1,y+1,x+size-1,y+size-1,outline='#ABB6C7',width=1)

    def _badge(self, x, y, width, text, tags):
        text = str(text)
        if '失败' in text or '需确认' in text or 'error' in tags:
            bg, fg, symbol = '#FFE9E9', '#D74347', '!'
        elif text.startswith(('完成','已完成')):
            bg, fg, symbol = ('#FFF3DF','#A96B13','!') if 'warning' in tags else ('#E2F6ED','#14805B','✓')
            if text == '完成': text = '已完成'
        elif '正在' in text or '保存' in text:
            bg, fg, symbol = '#E8F1FF', '#2269D4', '•'
        else: bg, fg, symbol = '#F0F3F8', '#68778C', '•'
        text = self._fit(text, width-34, self._heading_font)
        badge_width = min(width-6, self._heading_font.measure(text)+32)
        left = x+(width-badge_width)/2
        self._round(left,y-15,left+badge_width,y+15,bg,14)
        self.create_text(left+12,y,text=symbol,fill=fg,font=self._heading_font)
        self.create_text(left+24,y,text=text,fill=fg,font=self._heading_font,anchor='w')

    def _draw(self):
        self._pending = None
        self._layout(); super().delete('all')
        width, height = self.winfo_width(), self.winfo_height()
        ids = list(self._rows)
        for number in range(self._top, min(len(ids), self._top+self._page+1)):
            iid = ids[number]; row = self._rows[iid]
            top = self.header_height+(number-self._top)*self.row_height
            if iid in self._selected: self._round(0,top,width,top+self.row_height,'#EAF3FF',5)
            self.create_line(0,top+self.row_height,width,top+self.row_height,fill='#EEF2F8')
            center = top+self.row_height/2
            self._check(11-self._left,center-9,iid in self._selected)
            for key, value, (x,size) in zip(self.columns, row['values'], self._positions):
                if key == 'status': self._badge(x,center,size,value,row['tags'])
                else:
                    label = self._fit(value if value != '' else '—',size-18)
                    self.create_text(x+7 if key=='file' else x+size/2,center,text=label,
                        anchor='w' if key=='file' else 'center',fill='#21314F',font=self._font)
            if iid == self._focus and self.focus_get() == self:
                self.create_line(2,top+7,2,top+self.row_height-7,fill='#1772FF',width=2)
        self.create_rectangle(0,0,width,self.header_height,fill='#F1F6FD',outline='')
        for label,(x,size) in zip(self.labels,self._positions):
            self.create_text(x+7 if x==self._positions[0][0] else x+size/2,self.header_height/2,
                text=self._fit(label,size-10,self._heading_font),fill='#4E6180',font=self._heading_font,
                anchor='w' if x==self._positions[0][0] else 'center')
        all_selected = bool(ids) and len(self._selected)==len(ids)
        self._check(11-self._left,self.header_height/2-9,all_selected,bool(self._selected) and not all_selected)
        if self._yscroll:
            total=max(1,len(ids)); self._yscroll(self._top/total,min(1,(self._top+self._page)/total))
        if self._xscroll:
            self._xscroll(self._left/max(1,self._total_width),min(1,(self._left+width)/max(1,self._total_width)))

    def insert(self, parent, index, iid=None, values=(), tags=()):
        iid = str(iid if iid is not None else len(self._rows))
        self._rows[iid] = {'values':list(values), 'tags':tuple(tags)}
        self._schedule(); return iid

    def get_children(self, item=None): return tuple(self._rows)

    def delete(self, *items):
        changed = bool(self._selected.intersection(items))
        for item in items: self._rows.pop(str(item),None); self._selected.discard(str(item))
        if self._focus not in self._rows: self._focus = ''
        if self._anchor not in self._rows: self._anchor = ''
        self._schedule()
        if changed: self.event_generate('<<TreeviewSelect>>', when='tail')

    def item(self, item, option=None, **kwargs):
        row = self._rows[str(item)]
        for key,value in kwargs.items(): row[key] = list(value) if key=='values' else tuple(value)
        if kwargs: self._schedule()
        return row.get(option) if option else dict(row)

    def set(self, item, column=None, value=None):
        row = self._rows[str(item)]
        if column is None: return dict(zip(self.columns,row['values']))
        index = self.columns.index(column)
        if value is None: return row['values'][index]
        row['values'][index]=value; self._schedule()

    def selection(self): return tuple(i for i in self._rows if i in self._selected)

    def selection_set(self, *items):
        if len(items)==1 and isinstance(items[0],(list,tuple,set)): items=items[0]
        self._selected = {str(i) for i in items if str(i) in self._rows}
        self._schedule(); self.event_generate('<<TreeviewSelect>>')

    def focus(self, item=None):
        if item is not None: self._focus=str(item); self._schedule()
        return self._focus

    def see(self, item):
        self._layout(); index=list(self._rows).index(str(item))
        if index < self._top: self._top=index
        elif index >= self._top+self._page: self._top=index-self._page+1
        self._schedule()

    def yview(self, *args):
        self._layout()
        if not args: return (self._top/max(1,len(self._rows)),min(1,(self._top+self._page)/max(1,len(self._rows))))
        if args[0]=='moveto': self._top=round(float(args[1])*len(self._rows))
        else: self._top+=int(args[1])*(self._page if args[2]=='pages' else 1)
        self._schedule()

    def xview(self, *args):
        self._layout()
        if not args: return (self._left/max(1,self._total_width),min(1,(self._left+self.winfo_width())/max(1,self._total_width)))
        if args[0]=='moveto': self._left=round(float(args[1])*self._total_width)
        else: self._left=max(0,self._left+int(args[1])*30)
        self._schedule()

    def _wheel(self, event):
        self.yview('scroll',-1 if event.delta>0 else 1,'units'); return 'break'

    def _click(self, event):
        self.focus_set(); self._layout(); ids=list(self._rows)
        if event.y < self.header_height:
            if event.x+self._left<self.check_width: self._select_all()
            return 'break'
        index = self._top+int((event.y-self.header_height)//self.row_height)
        if index >= len(ids): return 'break'
        iid=ids[index]
        if event.state & 1 and self._anchor in ids:
            a,b=sorted((ids.index(self._anchor),index)); selected=set(ids[a:b+1])
        elif event.x+self._left<self.check_width or event.state & 4:
            selected=self._selected.symmetric_difference({iid}); self._anchor=iid
        else: selected={iid}; self._anchor=iid
        self._focus=iid; self.selection_set(selected); return 'break'

    def _select_all(self, event=None):
        self.selection_set(() if event is None and len(self._selected)==len(self._rows) else self.get_children()); return 'break'

    def _key(self, event):
        self._layout()
        ids=list(self._rows)
        if not ids: return 'break'
        index=ids.index(self._focus) if self._focus in ids else 0
        if event.keysym=='space':
            self.selection_set(self._selected.symmetric_difference({ids[index]})); return 'break'
        move={'Up':-1,'Down':1,'Prior':-self._page,'Next':self._page}.get(event.keysym,0)
        index = 0 if event.keysym=='Home' else len(ids)-1 if event.keysym=='End' else max(0,min(len(ids)-1,index+move))
        iid=ids[index]
        if event.state & 1 and self._anchor in ids:
            a,b=sorted((ids.index(self._anchor),index)); self.selection_set(ids[a:b+1])
        else: self.selection_set(iid); self._anchor=iid
        self._focus=iid; self.see(iid); return 'break'
