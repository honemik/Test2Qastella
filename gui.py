import json
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
        self.ans_json = {}
        self.mod_json = {}

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text='Select Folder', command=self.select_folder).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text='Parse Questions', command=self.do_questions).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text='Parse Answers', command=self.do_answers).grid(row=0, column=2, padx=5)
        tk.Button(btn_frame, text='Combine', command=self.do_combine).grid(row=0, column=3, padx=5)

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
            self.files = pdf_tool.recognize_files(folder)
            self.log_msg(f'Recognized files: {self.files}')

    def do_questions(self):
        if not self.folder or not self.files.get('question'):
            self.log_msg('Question file not set')
            return
        self.questions = pdf_tool.parse_questions(self.files['question'])
        self.log_msg(f'Parsed {len(self.questions)} questions')

    def do_answers(self):
        try:
            if self.files.get('answer'):
                self.ans_json = pdf_tool.parse_pdf_with_docling(self.files['answer'])
                self.log_msg('Parsed answer PDF')
            if self.files.get('modification'):
                self.mod_json = pdf_tool.parse_pdf_with_docling(self.files['modification'])
                self.log_msg('Parsed modification PDF')
        except Exception as e:
            self.log_msg(f'Docling error: {e}')

    def do_combine(self):
        if not self.questions:
            self.log_msg('No questions parsed')
            return
        combined = pdf_tool.combine(self.questions, self.ans_json, self.mod_json)
        out_path = filedialog.asksaveasfilename(defaultextension='.json')
        if out_path:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(combined, f, ensure_ascii=False, indent=2)
            self.log_msg(f'Saved combined JSON to {out_path}')

if __name__ == '__main__':
    app = App()
    app.mainloop()
