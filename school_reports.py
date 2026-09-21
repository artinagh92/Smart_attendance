"""School attendance reports. Python 3.9+, standard library only.
Run: python school_reports.py [path/to/attendance.db]
The attendance database is opened read-only; face encodings are never loaded.
"""
import csv
import datetime as dt
import queue
import sqlite3
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ALL = 'همه کلاس‌ها'
HEADERS = ('وضعیت', 'ساعت ورود', 'کلاس', 'نام دانش‌آموز', 'شناسه')


def read_report(filename, day):
    dt.date.fromisoformat(day)
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise ValueError('فایل دیتابیس پیدا نشد. attendance.db برنامه حضور و غیاب را انتخاب کنید.')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')  # One consistent, short read snapshot.
        sc = {r[1] for r in db.execute('PRAGMA table_info(students)')}
        ac = {r[1] for r in db.execute('PRAGMA table_info(attendance)')}
        if not {'id', 'name'}.issubset(sc) or not {'date'}.issubset(ac):
            raise ValueError('ساختار دیتابیس سازگار نیست؛ جدول students با id و name و جدول attendance با date لازم است.')
        by_id = 'student_id' in ac
        if not by_id and 'student_name' not in ac:
            raise ValueError('جدول attendance باید student_id یا student_name داشته باشد.')
        school_class = 'class_name' if 'class_name' in sc else "NULL AS class_name"
        students = [dict(r) for r in db.execute('SELECT id, name, ' + school_class + ' FROM students ORDER BY name, id')]
        fields = ['date', 'student_id' if by_id else 'student_name']
        fields += [c for c in ('class_name', 'enter_time') if c in ac]
        records = [dict(r) for r in db.execute('SELECT ' + ','.join(fields) + ' FROM attendance WHERE date=?', (day,))]
    finally:
        db.close()
    for s in students:
        s['name'] = str(s['name'] or '').strip()
        s['class_name'] = str(s['class_name'] or '').strip() or 'کلاس مشخص نشده'
    ids = {str(s['id']): s for s in students}
    by_name = defaultdict(list)
    by_pair = defaultdict(list)
    for s in students:
        by_name[s['name']].append(s)
        by_pair[(s['name'], s['class_name'])].append(s)
    times = defaultdict(list)
    uncertain = set()
    issues = []
    if not by_id:
        # Homonymous roster rows cannot be reliably matched by names.
        groups = by_pair.values() if 'class_name' in ac else by_name.values()
        for group in groups:
            if len(group) > 1:
                uncertain.update(str(s['id']) for s in group)
    for r in records:
        if by_id:
            s = ids.get(str(r['student_id']))
            matches = [s] if s else []
        else:
            name = str(r.get('student_name') or '').strip()
            cls = str(r.get('class_name') or '').strip()
            matches = by_pair.get((name, cls), []) if cls else by_name.get(name, [])
            if not matches:
                uncertain.update(str(s['id']) for s in by_name.get(name, []))
        if len(matches) != 1:
            uncertain.update(str(s['id']) for s in matches)
            issues.append('رکورد حضور بدون تطبیق یکتا با فهرست دانش‌آموزان')
            continue
        times[str(matches[0]['id'])].append(str(r.get('enter_time') or ''))
    rows = []
    for s in students:
        sid = str(s['id'])
        status = 'review' if sid in uncertain else 'present' if sid in times else 'missing'
        valid_times = sorted(t for t in times.get(sid, []) if t)
        rows.append(dict(id=sid, name=s['name'], class_name=s['class_name'],
                         time=valid_times[0][:8] if valid_times else '', status=status))
    return rows, len(records), len(issues)


def status_label(row, finalized):
    return {'present': 'حاضر', 'review': 'نیازمند بررسی',
            'missing': 'غایب — حضورگیری تکمیل‌شده' if finalized else 'حضور ثبت‌نشده'}[row['status']]


def class_summary(rows):
    groups = defaultdict(Counter)
    for r in rows:
        groups[r['class_name']]['total'] += 1
        groups[r['class_name']][r['status']] += 1
    return [(cls, c['total'], c['present'], c['missing'], c['review']) for cls, c in sorted(groups.items())]


class Reports(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('گزارش حضور و غیاب | کارکنان مدرسه')
        self.geometry('1150x760')
        self.minsize(900, 620)
        self.configure(bg='#eef3f7')
        self.rows = []
        self.messages = queue.Queue()
        self.busy = False
        self.loaded_key = None
        self.generation = 0
        self.finalized = tk.BooleanVar(value=False)
        self.file = tk.StringVar(value=str(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().with_name('attendance.db')))
        self.day = tk.StringVar(value=dt.date.today().isoformat())
        self.cls = tk.StringVar(value=ALL)
        self.search = tk.StringVar()
        self.notice = tk.StringVar(value='در حال خواندن اطلاعات…')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Tahoma', 10))
        style.configure('TFrame', background='#eef3f7')
        style.configure('TLabel', background='#eef3f7', foreground='#15394a')
        style.configure('TButton', padding=8)
        style.configure('Treeview', rowheight=32, font=('Tahoma', 10), background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Tahoma', 10, 'bold'), padding=8)
        style.configure('TNotebook.Tab', padding=(18, 10))
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='گزارش‌های مدرسه', font=('Tahoma', 23, 'bold'), anchor='e').pack(fill='x')
        ttk.Label(outer, text='حاضران · کلاس‌ها · وضعیت غیبت هر کلاس', anchor='e').pack(fill='x', pady=(4, 14))
        dbbar = ttk.Frame(outer)
        dbbar.pack(fill='x')
        ttk.Button(dbbar, text='انتخاب دیتابیس', command=self.pick_file).pack(side='right')
        ttk.Entry(dbbar, textvariable=self.file, state='readonly').pack(side='right', fill='x', expand=True, padx=8)
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=12)
        ttk.Label(controls, text='تاریخ میلادی YYYY-MM-DD').pack(side='right')
        self.date_entry = ttk.Entry(controls, textvariable=self.day, width=13, justify='center')
        self.date_entry.pack(side='right', padx=8)
        self.date_entry.bind('<Return>', lambda e: self.reload())
        ttk.Button(controls, text='امروز', command=self.today).pack(side='right')
        ttk.Button(controls, text='نمایش / به‌روزرسانی', command=self.reload).pack(side='right', padx=8)
        self.classbox = ttk.Combobox(controls, textvariable=self.cls, values=[ALL], state='readonly', width=24, justify='right')
        self.classbox.pack(side='right', padx=8)
        self.classbox.bind('<<ComboboxSelected>>', lambda e:self.render())
        ttk.Label(controls, text='کلاس').pack(side='right')
        searchbar = ttk.Frame(outer)
        searchbar.pack(fill='x')
        ttk.Label(searchbar, text='جست‌وجوی نام یا شناسه').pack(side='right')
        ttk.Entry(searchbar, textvariable=self.search, width=30, justify='right').pack(side='right', padx=8)
        self.search.trace_add('write', lambda *a:self.render())
        ttk.Checkbutton(searchbar, text='حضورگیری این روز کامل و بررسی شده است', variable=self.finalized, command=self.confirm).pack(side='right', padx=18)
        self.stats = ttk.Label(outer, anchor='e', font=('Tahoma', 12, 'bold'))
        self.stats.pack(fill='x', pady=16)
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        self.trees = {}
        for key, title in [('all','همه دانش‌آموزان'), ('present','حاضران'), ('missing','غیبت / ثبت‌نشده'), ('classes','کلاس‌ها'), ('review','نیازمند بررسی')]:
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text=title)
            headings = ('نیازمند بررسی','غیبت / ثبت‌نشده','حاضر','کل دانش‌آموزان','کلاس') if key=='classes' else HEADERS
            tree = ttk.Treeview(frame, columns=list(range(5)), show='headings', selectmode='browse')
            for i, h in enumerate(headings):
                tree.heading(str(i), text=h)
                tree.column(str(i), anchor='e', width=220 if i in (0,3) else 125, minwidth=70)
            scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            scroll.pack(side='left',fill='y')
            tree.pack(fill='both',expand=True)
            tree.tag_configure('present',foreground='#18704e')
            tree.tag_configure('missing',foreground='#a63c40')
            tree.tag_configure('review',foreground='#986000')
            self.trees[key] = tree
        self.trees['classes'].bind('<Double-1>', self.open_class)
        footer=ttk.Frame(outer)
        footer.pack(fill='x',pady=(12,0))
        ttk.Button(footer,text='خروجی CSV برای اکسل — همین صفحه',command=self.export).pack(side='right')
        ttk.Button(footer,text='راهنما',command=self.help).pack(side='right',padx=8)
        ttk.Label(outer,textvariable=self.notice,anchor='e',wraplength=1050).pack(fill='x',pady=(12,0))
        self.day.trace_add('write',self.invalidate)
        self.after(100,self.poll)
        self.after(200,self.reload)
        self.after(60000,self.auto_refresh)

    def invalidate(self,*args):
        self.finalized.set(False)
        self.loaded_key=None
        self.rows=[]
        self.render()
        self.notice.set('تاریخ تغییر کرده؛ دکمه نمایش را بزنید.')

    def pick_file(self):
        p=filedialog.askopenfilename(title='انتخاب attendance.db',filetypes=[('SQLite database','*.db *.sqlite *.sqlite3'),('All files','*.*')])
        if p:
            self.file.set(p)
            self.invalidate()
            self.reload()

    def today(self):
        self.day.set(dt.date.today().isoformat())
        self.reload()

    def reload(self):
        if self.busy:return
        day=self.day.get().strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))
        try:dt.date.fromisoformat(day)
        except ValueError:
            messagebox.showerror('تاریخ نامعتبر','تاریخ میلادی را مانند 2026-09-20 وارد کنید.');return
        if self.day.get()!=day:self.day.set(day)
        key=(self.file.get(),day)
        self.busy=True
        self.notice.set('در حال خواندن اطلاعات…')
        def worker():
            try:self.messages.put((key,read_report(*key),None))
            except Exception as e:self.messages.put((key,None,e))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            key,result,error=self.messages.get_nowait()
            self.busy=False
            if key==(self.file.get(),self.day.get().strip()):
                if error:
                    self.rows=[];self.loaded_key=None;self.finalized.set(False);self.render()
                    text='دیتابیس مشغول است؛ چند لحظه بعد به‌روزرسانی کنید.' if isinstance(error,sqlite3.OperationalError) and 'locked' in str(error) else str(error)
                    self.notice.set('خواندن گزارش انجام نشد: '+text)
                else:
                    previous=self.rows
                    self.rows,raw,issues=result
                    if previous!=self.rows:self.finalized.set(False)
                    self.loaded_key=key
                    classes=[ALL]+sorted({r['class_name'] for r in self.rows})
                    self.classbox['values']=classes
                    if self.cls.get() not in classes:self.cls.set(ALL)
                    self.render()
                    self.notice.set(f'آخرین خواندن: {dt.datetime.now():%H:%M:%S} | رکوردهای حضور: {raw} | رکوردهای مبهم: {issues} | تغییر اطلاعات، تأیید تکمیل حضورگیری را لغو می‌کند.')
            else:self.reload()
        except queue.Empty:pass
        self.after(100,self.poll)

    def auto_refresh(self):
        self.reload();self.after(60000,self.auto_refresh)

    def confirm(self):
        if self.finalized.get():
            if self.loaded_key is None or dt.date.fromisoformat(self.loaded_key[1])>dt.date.today():
                self.finalized.set(False)
                messagebox.showinfo('تأیید ممکن نیست','ابتدا گزارش یک روز گذشته یا امروز را بارگذاری کنید.');return
            ok=messagebox.askyesno('تأیید تکمیل حضورگیری',
                'آیا این روز برای همه کلاس‌های گزارش روز آموزشی بوده و تمام حضورها، از جمله ثبت دستی، بررسی شده‌اند؟\n\n'
                'با تأیید شما، افراد بدون حضور «غایب» نمایش داده می‌شوند. خطای دوربین، تعطیلی یا ثبت ناقص را ابتدا بررسی کنید.\n'
                'این تأیید فقط برای این گزارش است و در دیتابیس ذخیره نمی‌شود.')
            self.finalized.set(ok)
        self.render()

    def filtered(self):
        term=self.search.get().strip().casefold()
        return [r for r in self.rows if (self.cls.get()==ALL or r['class_name']==self.cls.get()) and
                (not term or term in r['name'].casefold() or term in r['id'])]

    def render(self):
        if not self.trees:return
        rows=self.filtered()
        counts=Counter(r['status'] for r in rows)
        missing='غایب' if self.finalized.get() else 'حضور ثبت‌نشده'
        self.stats.config(text=f"کل: {len(rows)}     |     حاضر: {counts['present']}     |     {missing}: {counts['missing']}     |     نیازمند بررسی: {counts['review']}")
        for tree in self.trees.values():tree.delete(*tree.get_children())
        for r in rows:
            vals=(status_label(r,self.finalized.get()),r['time'],r['class_name'],r['name'],r['id'])
            self.trees['all'].insert('', 'end', values=vals,tags=(r['status'],))
            self.trees[r['status']].insert('', 'end', values=vals,tags=(r['status'],))
        self.trees['classes'].heading('1',text=missing)
        for cls,total,present,absent,review in class_summary(rows):
            self.trees['classes'].insert('','end',values=(review,absent,present,total,cls))

    def open_class(self,event):
        tree=self.trees['classes'];item=tree.focus()
        if item:
            self.cls.set(tree.item(item,'values')[4]);self.render();self.tabs.select(2)

    def export(self):
        if self.loaded_key is None:
            messagebox.showinfo('گزارش آماده نیست','ابتدا گزارش را بارگذاری کنید.');return
        key=list(self.trees)[self.tabs.index(self.tabs.select())]
        tree=self.trees[key]
        p=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=f'school_{key}_{self.loaded_key[1]}.csv',filetypes=[('Excel-compatible CSV','*.csv')])
        if not p:return
        def safe(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
        try:
            with open(p,'w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f)
                writer.writerow(['تاریخ میلادی','وضعیت حضورگیری']+[tree.heading(str(i),'text') for i in range(5)])
                for iid in tree.get_children():
                    writer.writerow([self.loaded_key[1],'تکمیل‌شده با تأیید مسئول' if self.finalized.get() else 'تأیید نشده']+[safe(v) for v in tree.item(iid,'values')])
            messagebox.showinfo('ذخیره شد','گزارش همین صفحه با فیلترهای فعلی ذخیره شد. فایل را با Excel باز کنید.')
        except OSError as e:messagebox.showerror('ذخیره انجام نشد',str(e))

    def help(self):
        messagebox.showinfo('راهنما',
            '۱. فایل attendance.db اصلی مدرسه را انتخاب کنید.\n'
            '۲. تاریخ میلادی و کلاس را انتخاب کنید.\n'
            '۳. با دوبار کلیک روی کلاس، افراد فاقد حضور همان کلاس نمایش داده می‌شوند.\n'
            '۴. پس از بررسی کامل حضورگیری، گزینه تأیید را فعال کنید.\n'
            '۵. خروجی اکسل‌خوان برای صفحه و فیلتر فعلی ذخیره می‌شود.\n\n'
            'حضور تکراری فقط یک بار شمارش می‌شود؛ اولین ساعت ورود نمایش داده می‌شود. نام‌های مبهم در «نیازمند بررسی» هستند.\n'
            'آمار بر مبنای فهرست فعلی دانش‌آموزان است؛ برای تاریخ‌های قدیمی تغییر کلاس‌ها را در نظر بگیرید.\n'
            'این پنل محلی حساب کاربری و دسترسی از راه دور ندارد. فقط روی کامپیوتر مجاز کارکنان اجرا شود.\n'
            'دیتابیس فقط خوانده می‌شود و اطلاعات چهره اصلاً بارگذاری نمی‌شود. برای غیبت موجه/غیرموجه داده‌ای در ساختار فعلی وجود ندارد.')


if __name__=='__main__':
    Reports().mainloop()
