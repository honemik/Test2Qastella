import os
import tkinter as tk
from tkinter import filedialog, scrolledtext

import pdf_tool

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PDF QA Tool')
        self.geometry('600x400')
        self.folder = None
        self.questions = []
        self.ans_md = ''
        self.mod_md = ''
        self.sets = {}
        self.set_var = tk.StringVar()
        self.option_menu = None

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text='Select Folder', command=self.select_folder).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text='Parse Questions', command=self.do_questions).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text='Parse Answers', command=self.do_answers).grid(row=0, column=2, padx=5)
        tk.Button(btn_frame, text='Combine', command=self.do_combine).grid(row=0, column=3, padx=5)
        tk.Button(btn_frame, text='Preview', command=self.preview_questions).grid(row=0, column=4, padx=5)

        self.log = scrolledtext.ScrolledText(self, state='disabled')
        self.log.pack(expand=True, fill='both')

    def log_msg(self, msg: str):
        self.log.configure(state='normal')
        self.log.insert(tk.END, msg + '\n')
        self.log.configure(state='disabled')
        self.log.see(tk.END)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder = folder
            self.log_msg(f'Selected folder: {folder}')
            self.sets = pdf_tool.recognize_files(folder)
            keys = list(self.sets.keys())
            if not keys:
                self.log_msg('No PDF files found')
                return
            if self.option_menu:
                self.option_menu.destroy()
            self.set_var.set(keys[0])
            self.files = self.sets[self.set_var.get()]
            self.option_menu = tk.OptionMenu(self, self.set_var, *keys, command=self.change_set)
            self.option_menu.pack()
            self.log_msg(f'Recognized sets: {keys}')

    def do_questions(self):
        if not self.folder or not self.files.get('question'):
            self.log_msg('Question file not set')
            return
        self.questions = pdf_tool.parse_questions(self.files['question'])
        base = os.path.splitext(os.path.basename(self.files['question']))[0]
        path = os.path.join(pdf_tool.OUT_DIR, f"questions_{base}.json")
        self.log_msg(f'Parsed {len(self.questions)} questions -> {path}')
        self.preview_questions()

    def do_answers(self):
        try:
            if self.files.get('answer'):
                self.ans_md = pdf_tool.parse_pdf_with_docling(self.files['answer'])
                path = os.path.join(pdf_tool.OUT_DIR, f"{os.path.splitext(os.path.basename(self.files['answer']))[0]}.md")
                self.log_msg(f'Parsed answer PDF -> {path}')
                self.preview_text(self.ans_md, 'Answer Markdown')
            if self.files.get('modification'):
                self.mod_md = pdf_tool.parse_pdf_with_docling(self.files['modification'])
                path = os.path.join(pdf_tool.OUT_DIR, f"{os.path.splitext(os.path.basename(self.files['modification']))[0]}.md")
                self.log_msg(f'Parsed modification PDF -> {path}')
                self.preview_text(self.mod_md, 'Modification Markdown')
        except Exception as e:
            self.log_msg(f'Docling error: {e}')

    def do_combine(self):
        if not self.questions:
            self.log_msg('No questions parsed')
            return
        combined = pdf_tool.combine(self.questions, self.ans_md, self.mod_md, set_name=self.set_var.get())
        out_path = os.path.join(pdf_tool.OUT_DIR, f"combined_{self.set_var.get()}.json")
        self.log_msg(f'Saved combined JSON to {out_path}')
        self.preview_questions(combined)

    def change_set(self, value):
        self.files = self.sets[value]
        self.log_msg(f'Using set: {value}')

    def preview_questions(self, questions=None):
        if questions is None:
            questions = self.questions
        if not questions:
            return
        win = tk.Toplevel(self)
        win.title('Preview')
        text = scrolledtext.ScrolledText(win)
        text.pack(side='left', fill='both', expand=True)
        img_label = tk.Label(win)
        img_label.pack(side='right')

        def show(idx=0):
            q = questions[idx]
            text.delete('1.0', tk.END)
            text.insert(tk.END, f"Q{q['id']}\n{q['question']}\n")
            for k, v in q.get('options', {}).items():
                text.insert(tk.END, f"{k}. {v}\n")
            if q.get('answer'):
                text.insert(tk.END, f"Ans: {q['answer']}\n")
            if q.get('modification'):
                text.insert(tk.END, f"Mod: {q['modification']}\n")
            if q.get('images'):
                data = q['images'][0]
                photo = tk.PhotoImage(data=data)
                img_label.configure(image=photo)
                img_label.image = photo
            else:
                img_label.configure(image='', text='No image')
                img_label.image = None
            win.title(f'Preview Q{q["id"]}')

        btn_frame = tk.Frame(win)
        btn_frame.pack(side='bottom')
        idx = {'value': 0}

        def next_q():
            idx['value'] = (idx['value'] + 1) % len(questions)
            show(idx['value'])

        tk.Button(btn_frame, text='Next', command=next_q).pack()
        show(0)

    def preview_text(self, text, title='Preview'):
        win = tk.Toplevel(self)
        win.title(title)
        st = scrolledtext.ScrolledText(win)
        st.pack(expand=True, fill='both')
        st.insert(tk.END, text)

if __name__ == '__main__':
    app = App()
    app.mainloop()
