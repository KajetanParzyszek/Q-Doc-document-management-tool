###   Importing necassary packages   ###

import sqlite3
import requests
import PyPDF2
import fitz # PyMuPDF
import re
import os
import sys
import tkinter as tk
import subprocess as sp

from tkinter     import ttk, simpledialog, filedialog
from tkinterdnd2 import TkinterDnD, DND_FILES
from PIL         import Image, ImageTk
from ctypes      import windll


###   PDF metadata extraction functions   ###

def get_metadata_from_doi(doi):
    
    base_url = 'https://api.crossref.org/works/'
    url = f'{base_url}{doi}'

    try:
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()

        if 'message' in data:
            
            metadata = data['message']

            title        = metadata.get('title', '')      
            authors_list = [author.get('given', '') + ' ' + author.get('family', '') for author in metadata.get('author', [])]
            journal      = metadata.get('container-title', [''])
            year         = metadata.get('published-print', {}).get('date-parts', [['', '', '']])[0]       


            def get_title(title):
                if title:
                    if len(title) > 0:
                        title = title[0] 
                else:
                    title = 'Unknown title'
                return title

            def get_journal(journal):
                if journal:
                    if len(journal) > 0:
                        journal = journal[0] 
                else:
                    journal = 'Unknown journal'
                return journal
          
            title = get_title(title)
            
            journal = get_journal(journal)
            
            if year:
                year = year[0] if year[0] else 0

            authors = ''
            for i in range(len(authors_list)):
                if i != len(authors_list) - 1:
                    authors += str(f'{authors_list[i]}, ')
                else:
                    authors += str(authors_list[i])
            if authors == '':
                authors = 'Unknown authors'
            
            return {'title' : title, 'authors' : authors, 'journal' : journal, 'year' : year, 'doi' : doi}
        
        else:
            return None

    # Exception blocks
    except requests.exceptions.HTTPError as errh:
        if len(doi) > 1:
            doi = doi[:-1]
            return get_metadata_from_doi(doi)
        else:
            print(f'HTTP Error: {errh}')
            
    except requests.exceptions.ConnectionError as errc:
        print(f'Error Connecting: {errc}')
    
    except requests.exceptions.Timeout as errt:
        print(f'Timeout Error: {errt}')
    
    except requests.exceptions.RequestException as err:
        print(f'An error occurred: {err}')

def get_doi_from_pdf(pdf_path):

    try:
        with open(pdf_path, 'rb') as file:
            
            pdf_reader = PyPDF2.PdfReader(file)
            num_pages = len(pdf_reader.pages)
            
            doi = ''
            page_num = 0
            
            while (not doi) and (page_num < num_pages):
                
                page = pdf_reader.pages[page_num]
                page_text = page.extract_text()
                doi = re.findall(r"\b(10\.\d{4,}(?:\.\d+)*\/\S+(?:(?!['\"])\S)*)\b", page_text)
                page_num += 1
    
    except Exception as e:
        print(f'Error: {e}')
    
    return doi[0]

def get_metadata_from_pdf(pdf_path):
    pdf_doi = get_doi_from_pdf(pdf_path)
    metadata = get_metadata_from_doi(pdf_doi)
    return metadata
    
def extract_paths(raw_path_string):
    all_paths    = []
    current_path = ''
    for symbol in raw_path_string:
        if symbol == '}':
            all_paths.append(current_path)
        elif symbol == '{':
            current_path = ''
        else:
            current_path += symbol
    return all_paths

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS2
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)




### Database functions 

#### Connection

#Connecting to database: (If the database or the tables don't exist yet, they are created)

def connect_to_database():
    connection = sqlite3.connect(get_resource_path('data\\pdf_tool.db'))
    cursor = connection.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pdf (
            pdf_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            title    TEXT,
            authors  TEXT,
            journal  TEXT,
            year     INT,
            doi      TEXT UNIQUE,
            path     TEXT UNIQUE,
            archived INT,
            label    TEXT,
            CHECK (archived IN (0, 1)),
            CHECK (label IN ('Already read', 'Being read', 'To be read'))
        )''')
    cursor.execute('''   
        CREATE TABLE IF NOT EXISTS queue (
            queue_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE
        )''')
    cursor.execute('''   
        CREATE TABLE IF NOT EXISTS queue_pdf (
            queue_id INTEGER,
            pdf_id   INTEGER,
            position INTEGER,
            CONSTRAINT unique_queue_pdf UNIQUE (queue_id, pdf_id)
        )''')
    cursor.execute('''   
        CREATE TABLE IF NOT EXISTS note (
            note_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_id    INTEGER,
            note_text TEXT,
            CONSTRAINT unique_pdf_note UNIQUE (pdf_id, note_text)
        )''')
    cursor.execute('''   
        CREATE TABLE IF NOT EXISTS tag (
            tag_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_text TEXT,
            CONSTRAINT unique_tag UNIQUE (tag_text)
        )''')
    cursor.execute('''   
        CREATE TABLE IF NOT EXISTS tag_pdf (
            tag_id   INTEGER,
            pdf_id    INTEGER,
            CONSTRAINT unique_pdf_tag UNIQUE (pdf_id, tag_id)
        )''')

    connection.commit()
    return connection

#### PDFs

#Adding a PDF

def add_pdf(connection, path):

    metadata = get_metadata_from_pdf(path)

    title, authors, journal, year, doi = tuple(metadata.values())
    
    cursor = connection.cursor()
    cursor.execute('INSERT INTO pdf (title, authors, journal, year, doi, path, archived, label) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
                   (title, authors, journal, year, doi, path, 0, 'To be read'))
    connection.commit()

#Updating PDF's metadata

def update_pdf(connection, column, new_value, pdf_id):
    cursor = connection.cursor()
    cursor.execute(f'UPDATE pdf SET {column} = ? WHERE pdf_id = ?', (new_value, pdf_id))
    connection.commit()

#Displaying metadata of all PDFs

def show_all_pdfs(connection):
    cursor = connection.cursor()
    cursor.execute('SELECT title, authors, journal, year FROM pdf')
    rows = cursor.fetchall()
    return rows

#Displaying metadata of one PDF

def show_pdf(connection, pdf_id):
    cursor = connection.cursor()
    cursor.execute('SELECT title, authors, journal, year, doi, path, label FROM pdf WHERE pdf_id = ?', (pdf_id,))
    record = cursor.fetchall()
    return record[0]


#### Queues

#Adding a queue

def add_queue(connection, queue_name):
    cursor = connection.cursor()
    cursor.execute('INSERT INTO queue (name) VALUES (?)', (queue_name,))
    connection.commit()

#Renaming a queue

def rename_queue(connection, old_name, new_name):
    cursor = connection.cursor()
    cursor.execute('UPDATE queue SET name = ? WHERE name = ?', (new_name, old_name))
    connection.commit()
    
#Deleting a queue

def delete_queue(connection, queue_name):
    cursor = connection.cursor()
    cursor.execute('''DELETE FROM queue_pdf WHERE queue_id = (SELECT q.queue_id 
                                                              FROM queue AS q
                                                              WHERE q.name = ?)''', (queue_name,))
    cursor.execute('DELETE FROM queue WHERE name = ?', (queue_name,))
    connection.commit()

def get_queue_idx(connection, queue_name):
    cursor = connection.cursor()
    queue_idx = cursor.execute('SELECT queue_id FROM queue WHERE name = ?', (queue_name,)).fetchall()[0][0]
    return queue_idx



#Showing the list of all queues

def show_queues(connection):
    cursor = connection.cursor()
    cursor.execute('SELECT * FROM queue')
    rows = cursor.fetchall()
    return rows



#### PDFs and queues

#Adding a PDF to a queue

def show_queue_files(connection, queue_id):
    cursor = connection.cursor()
    raw_files = cursor.execute('SELECT pdf_id FROM queue_pdf WHERE queue_id = ?', (queue_id,)).fetchall()
    existing_files = [file[0] for file in raw_files]
    return existing_files


def pdf_to_queue(connection, queue_id, pdf_id):
    cursor = connection.cursor()
    cursor.execute('UPDATE queue_pdf SET position = position + 1 WHERE queue_id = ?', (queue_id,))
    cursor.execute('INSERT INTO queue_pdf VALUES (?, ?, ?)', (queue_id, pdf_id, 1))
    connection.commit()

#Deleting a PDF from a queue

def delete_from_queue(connection, queue_id, pdf_id):
    cursor = connection.cursor()
    cursor.execute('''UPDATE queue_pdf SET position = position - 1 
                      WHERE queue_id = ? AND position > (SELECT position FROM queue_pdf WHERE (queue_id = ? AND pdf_id = ?))''', 
                      (queue_id, queue_id, pdf_id))
    cursor.execute('DELETE FROM queue_pdf WHERE (queue_id = ? AND pdf_id = ?)', (queue_id, pdf_id))
    connection.commit()

#Displaying the contents of one queue

def show_queue(connection, queue_id):
    cursor = connection.cursor()
    cursor.execute('''SELECT qp.position, p.title, p.authors, p.journal, p.year
                      FROM queue_pdf AS qp
                      JOIN pdf AS p ON qp.pdf_id = p.pdf_id
                      WHERE qp.queue_id = ?
                      ORDER BY qp.position''', (queue_id,))
    rows = cursor.fetchall()
    return rows

#Editing the position of a PDF in a queue

def edit_position(connection, queue_id, pdf_id, new_position):
    cursor = connection.cursor()

    length = cursor.execute('SELECT COUNT(*) FROM queue_pdf WHERE queue_id = ?', (queue_id,)).fetchall()
    
    if new_position <= length[0][0] and new_position > 0 and type(new_position) == int:
    
        cursor.execute('''UPDATE queue_pdf SET position = position + 1 
                          WHERE (queue_id = ? AND position < (SELECT position FROM queue_pdf WHERE queue_id = ? AND pdf_id = ?) 
                          AND position >= ?)''', (queue_id, queue_id, pdf_id, new_position))
        cursor.execute('''UPDATE queue_pdf SET position = position - 1 
                          WHERE (queue_id = ? AND position > (SELECT position FROM queue_pdf WHERE queue_id = ? AND pdf_id = ?) 
                          AND position <= ?)''', (queue_id, queue_id, pdf_id, new_position))
        cursor.execute('UPDATE queue_pdf SET position = ? WHERE (queue_id = ? AND pdf_id = ?)', (new_position, queue_id, pdf_id))
        connection.commit()
        

#### Archive

#Moving a PDF to the archive

def add_to_archive(connection, queue_id, pdf_id):
    cursor = connection.cursor()
    cursor.execute('''UPDATE queue_pdf SET position = position - 1 
                      WHERE queue_id = ? AND position > (SELECT position FROM queue_pdf WHERE (queue_id = ? AND pdf_id = ?))''', 
                      (queue_id, queue_id, pdf_id))
    cursor.execute('''UPDATE pdf SET archived = ? WHERE pdf_id = ?''', (1, pdf_id))
    connection.commit()

#Restoring a PDF from the archive

def restore_pdf(connection, pdf_id):
    cursor = connection.cursor()
    cursor.execute('''UPDATE pdf SET archived = ? WHERE pdf_id = ?''', (0, pdf_id))
    connection.commit()

#Deleting a PDF from the database

def delete_pdf(connection, pdf_id):
    cursor = connection.cursor()
    cursor.execute('DELETE FROM pdf WHERE pdf_id = ?', (pdf_id,))
    connection.commit()


def show_table(connection, table_name, sorting, order):
    cursor = connection.cursor()
    if table_name == 'pdf':
        rows = cursor.execute(f'''SELECT title, authors, journal, year, label
                                  FROM pdf
                                  WHERE (archived = ?)
                                  ORDER BY {sorting} {order}''', (0,)).fetchall()
    elif table_name == 'archive':
        rows = cursor.execute('SELECT title, authors, journal, year FROM pdf WHERE archived = ?', (1,)).fetchall()
    else:
        rows = cursor.execute('''SELECT position, title, authors, journal, year, label
                                 FROM pdf AS p
                                 JOIN queue_pdf AS qp ON p.pdf_id = qp.pdf_id
                                 JOIN queue     AS q  ON qp.queue_id = q.queue_id
                                 WHERE (q.name = ?) AND (p.archived = ?)
                                 ORDER BY qp.position''', (table_name, 0)).fetchall()
    return rows


def get_file_path(connection, title, authors, journal, year):
    cursor = connection.cursor()
    file_path = cursor.execute('''SELECT path
                                  FROM pdf
                                  WHERE (title = ? AND authors = ? AND journal = ? AND year = ?)''',
                               (title, authors, journal, year)).fetchall()
    return file_path[0][0]

def get_file_id_from_path(connection, pdf_path):
    cursor = connection.cursor()
    file_id = cursor.execute('SELECT pdf_id FROM pdf WHERE path = ?', (pdf_path,)).fetchall()
    return file_id[0][0]

def get_file_id(connection, title, authors, journal, year):
    cursor = connection.cursor()
    file_id = cursor.execute('''SELECT pdf_id
                                FROM pdf
                                WHERE (title = ? AND authors = ? AND journal = ? AND year = ?)''',
                                (title, authors, journal, year)).fetchall()
    return file_id[0][0]

def get_queue_id(connection, queue_name):
    cursor = connection.cursor()
    file_path = cursor.execute('SELECT queue_id FROM queue WHERE name = ?', (queue_name,)).fetchall()
    return file_path[0][0]


def get_file_position(connection, queue_name, pdf_id):
    cursor = connection.cursor()
    file_path = cursor.execute('''SELECT qp.position 
                                  FROM queue_pdf AS qp
                                  JOIN queue AS q ON qp.queue_id = q.queue_id
                                  WHERE (q.name = ? AND qp.pdf_id = ?)''', (queue_name, pdf_id)).fetchall()
    return file_path[0][0]

def edit_pdf_label(connection, pdf_id, new_label):
    cursor = connection.cursor()
    cursor.execute('UPDATE pdf SET label = ? WHERE pdf_id = ?', (new_label, pdf_id))
    connection.commit()


def get_pdf_notes(connection, pdf_id):
    cursor = connection.cursor()
    cursor.execute('SELECT note_text FROM note WHERE pdf_id = ? ORDER BY note_id', (pdf_id,))
    notes = cursor.fetchall()
    return notes

def get_note_id(connection, pdf_id, note_text):
    cursor = connection.cursor()
    cursor.execute('SELECT note_id FROM note WHERE (pdf_id = ?) AND (note_text = ?)', (pdf_id, note_text))
    note_id = cursor.fetchall()[0][0]
    return note_id

def get_note_text(connection, note_id):
    cursor = connection.cursor()
    cursor.execute('SELECT note_text FROM note WHERE note_id = ?', (note_id,))
    note_text = cursor.fetchall()[0][0]
    return note_text
    
def edit_note(connection, note_id, new_text):
    cursor = connection.cursor()
    cursor.execute('UPDATE note SET note_text = ? WHERE note_id = ?', (new_text, note_id))
    connection.commit()    

def add_note(connection, pdf_id, note_text):
    cursor = connection.cursor()
    cursor.execute('INSERT INTO note (pdf_id, note_text) VALUES (?, ?)', (pdf_id, note_text))
    connection.commit()

def delete_note(connection, note_id):
    cursor = connection.cursor()
    cursor.execute('DELETE FROM note WHERE note_id = ?', (note_id,))
    connection.commit()

def show_all_tags(connection):
    cursor = connection.cursor()
    tags = cursor.execute('SELECT tag_text FROM tag').fetchall()
    return [tag[0] for tag in tags]

def assign_pdf_tag(connection, pdf_id, tag_id):
    cursor = connection.cursor()
    cursor.execute('INSERT INTO tag_pdf (tag_id, pdf_id) VALUES (?, ?)', (tag_id, pdf_id))
    connection.commit()

def delete_pdf_tag(connection, pdf_id, tag_id):
    cursor = connection.cursor()
    cursor.execute('DELETE FROM tag_pdf WHERE (tag_id = ? AND pdf_id = ?)', (tag_id, pdf_id))
    connection.commit()
    
def show_pdf_tags(connection, pdf_id):
    cursor = connection.cursor()
    tags = cursor.execute('''SELECT tag_text FROM tag WHERE tag_id IN 
                            (SELECT tag_id FROM tag_pdf WHERE pdf_id = ?)''', (pdf_id,)).fetchall()
    return [tag[0] for tag in tags]

def get_tag_id(connection, tag_text):
    cursor = connection.cursor()
    tag_id = cursor.execute('SELECT tag_id FROM tag WHERE tag_text = ?', (tag_text,)).fetchall()
    return tag_id[0][0]

def add_tag(connection, tag_text):
    cursor = connection.cursor()
    cursor.execute('INSERT INTO tag (tag_text) VALUES (?)', (tag_text,))
    connection.commit()

def delete_tag(connection, tag_text):
    cursor = connection.cursor()
    cursor.execute('DELETE FROM tag WHERE tag_text = ?', (tag_text,))
    connection.commit()

def edit_tag(connection, old_tag_text, new_tag_text):
    cursor = connection.cursor()
    cursor.execute('UPDATE tag SET tag_text = ? WHERE tag_text = ?', (new_tag_text, old_tag_text))
    connection.commit()
    




connection = connect_to_database()


class TagManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
    
        self.title('Tag manager')
        self.geometry('500x500')
        self.iconphoto(True, tk.PhotoImage(file=get_resource_path('images\\q_logo.png')))

        self.current_tag = None

        frame = tk.Frame(self)
        frame.pack(pady=10, fill=tk.BOTH, expand=True)
    
        # Button to get selected values
        add_tag_button = tk.Button(frame, text='Add new tag', command=self.add_new_tag, font=('Arial',14))
        add_tag_button.pack()
    
        # Create a scrollbar
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
        # Create a canvas to contain the checkbuttons
        self.canvas = tk.Canvas(frame, yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind('<Configure>', self.update_window_size)
        
        # Attach the scrollbar to the canvas
        scrollbar.config(command=self.canvas.yview)
    
        # Create a frame inside the canvas to hold the checkbuttons
        self.inner_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW, tags='filters')

        self.tags = show_all_tags(connection)
        self.labels = []
        for i, tag in enumerate(self.tags):
            tag_label = tk.Label(self.inner_frame, text=tag, bg='dimgray', fg='white', anchor='w', justify=tk.LEFT, wraplength=400,
                                     padx=10, pady=5, font=('Arial',14))
            tag_label.pack(fill=tk.X, pady=3, padx=5)
            tag_label.bind("<Button-3>", self.show_tag_context_menu)
            self.labels.append(tag_label)     

        self.update_canvas_scroll_region(None)

    def add_new_tag(self):
        def add_new_tag_function(new_tag_name):
            if new_tag_name in self.tags:
                info_label.configure(text='Such tag already exists', fg='red')
            else:
                add_tag(connection, new_tag_name)
                info_label.configure(text='Tag added succesfully', fg='green')
                new_tag_label = tk.Label(self.inner_frame, text=new_tag_name, bg='dimgray', fg='white', anchor='w', justify=tk.LEFT, wraplength=200,
                                     padx=10, font=('Arial',14))
                new_tag_label.pack(fill=tk.X, pady=3, padx=5)
                new_tag_label.bind("<Button-3>", self.show_tag_context_menu)
                self.tags.append(new_tag_name)
                self.labels.append(new_tag_label)
                self.update()
            self.update_canvas_scroll_region(None)
            self.update_window_size(None)
                    
        x = (screen_width  - 300) // 2
        y = (screen_height - 150) // 2
            
        # Create a dialog window
        dialog = tk.Toplevel()
        dialog.geometry(f'300x200+{x}+{y}')
        dialog.title("Add new tag")
            
        # Label for the drop-down menu
        select_label = tk.Label(dialog, text="Enter new tag:", font=('Arial', 12))
        select_label.pack(pady=5)
            
        # Create the drop-down menu
        tag_entry = tk.Text(dialog, font=('Arial', 12), width=30, height=1)
        tag_entry.pack(pady=5, padx=10)
            
        # Button to confirm selection
        confirm_button = tk.Button(dialog, text="Add tag", font=('Arial', 13), 
                                   command=lambda: add_new_tag_function(tag_entry.get("1.0", tk.END).rstrip('\n')))
        confirm_button.pack(pady=5)
    
        info_label = tk.Label(dialog, text='', font=('Arial', 12))
        info_label.pack(pady=5)
            
        # Run the dialog window
        dialog.mainloop()

        menu_frame.all_files_command()
        
    def show_tag_context_menu(self, event):
        label_widget = event.widget
        self.current_label = label_widget
        self.current_tag   = self.current_label.cget('text')
        
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Edit tag",   command=self.edit_tag_function)
        self.context_menu.add_command(label="Delete tag", command=self.delete_tag_function)
        self.context_menu.post(event.x_root, event.y_root)

    def edit_tag_function(self):
        
        def edit_tag_subfunction(new_tag_name):
            if new_tag_name in self.tags:
                info_label.configure(text='Such tag already exists', fg='red')
            else:
                edit_tag(connection, self.current_tag, new_tag_name)
                self.current_label.configure(text=new_tag_name)
                self.current_tag = self.current_label.cget('text')
                self.tags = show_all_tags(connection)
                self.update()
                dialog.destroy()
                         
        x = (screen_width  - 300) // 2
        y = (screen_height - 150) // 2
            
        # Create a dialog window
        dialog = tk.Toplevel()
        dialog.geometry(f'300x200+{x}+{y}')
        dialog.title("Edit tag")
            
        # Label for the drop-down menu
        select_label = tk.Label(dialog, text="Modify existing tag:", font=('Arial', 12))
        select_label.pack(pady=5)
            
        # Create the drop-down menu
        tag_entry = tk.Text(dialog, font=('Arial', 12), width=30, height=1)
        tag_entry.insert('1.0', self.current_tag)
        tag_entry.pack(pady=5, padx=10)
            
        # Button to confirm selection
        confirm_button = tk.Button(dialog, text="Edit tag", font=('Arial', 13), 
                                   command=lambda: edit_tag_subfunction(tag_entry.get("1.0", tk.END).rstrip('\n')))
        confirm_button.pack(pady=5)
    
        info_label = tk.Label(dialog, text='', font=('Arial', 12))
        info_label.pack(pady=5)
            
        # Run the dialog window
        dialog.mainloop()
        
    def delete_tag_function(self):
        delete_tag(connection, self.current_tag)
        self.current_label.destroy()
        self.tags = show_all_tags(connection)
        self.update_canvas_scroll_region(None)
        self.update_window_size(None)
        self.update()
    
    def update_canvas_scroll_region(self, event):
        # Update the canvas scroll region to match the inner frame's size
        self.inner_frame.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def update_window_size(self, event):
        self.canvas.itemconfig('filters', width=self.canvas.winfo_width())



class FilteringWindow(tk.Toplevel):

    def __init__(self, parent):
        super().__init__(parent)
    
        self.title('Filtering documents')
        self.geometry('500x500')
        self.iconphoto(True, tk.PhotoImage(file=get_resource_path('images\\q_logo.png')))
        
        # Create a frame to hold the button and checkbuttons
        frame = tk.Frame(self)
        frame.pack(pady=10, fill=tk.BOTH, expand=True)
    
        # Button to get selected values
        get_values_button = tk.Button(frame, text='Show results', command=self.get_selected_values, font=('Arial',14))
        get_values_button.pack()
    
        # Create a scrollbar
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
        # Create a canvas to contain the checkbuttons
        self.canvas = tk.Canvas(frame, yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind('<Configure>', self.update_window_size)
        
        # Attach the scrollbar to the canvas
        scrollbar.config(command=self.canvas.yview)
    
        # Create a frame inside the canvas to hold the checkbuttons
        self.inner_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW, tags='filters')

        self.tags      = show_all_tags(connection)
        self.colors    = ['white', '#d9cf9a']
        self.values    = []
        self.buttons   = []
        for i, tag in enumerate(self.tags):
            filter_button = tk.Button(self.inner_frame, text=tag, bg=self.colors[int(tag in menu_frame.filters)], fg='black',
                                      padx=10, command=lambda b=i: self.filter_button_click(b), font=('Arial',14), anchor='w')
            filter_button.pack(fill=tk.X)
            self.buttons.append(filter_button)
            self.values.append(int(tag in menu_frame.filters))     

        self.update_canvas_scroll_region(None)

    def get_selected_values(self):
        selected_values = []
        for i, value in enumerate(self.values):
            if value == 1:
                selected_values.append(self.buttons[i].cget('text'))
        menu_frame.filters = selected_values
        menu_frame.all_files_command()
        self.destroy()

    def filter_button_click(self, idx):
        self.values[idx] = (self.values[idx] + 1) % 2
        self.buttons[idx].configure(bg=self.colors[self.values[idx]])

    def update_canvas_scroll_region(self, event):
        # Update the canvas scroll region to match the inner frame's size
        self.inner_frame.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def update_window_size(self, event):
        self.canvas.itemconfig('filters', width=self.canvas.winfo_width())


class AssignTagsWindow(tk.Toplevel):

    def __init__(self, parent, pdf_id):
        super().__init__(parent)
    
        self.title('Assigning tags to file')
        self.geometry('500x500')
        self.iconphoto(True, tk.PhotoImage(file=get_resource_path('images\\q_logo.png')))

        self.pdf_id = pdf_id
        
        # Create a frame to hold the button and checkbuttons
        frame = tk.Frame(self)
        frame.pack(pady=10, fill=tk.BOTH, expand=True)
    
        # Button to get selected values
        get_values_button = tk.Button(frame, text='Confirm changes', command=self.confirm_tags, font=('Arial',14))
        get_values_button.pack()
    
        # Create a scrollbar
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
        # Create a canvas to contain the checkbuttons
        self.canvas = tk.Canvas(frame, yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind('<Configure>', self.update_window_size)
        
        # Attach the scrollbar to the canvas
        scrollbar.config(command=self.canvas.yview)
    
        # Create a frame inside the canvas to hold the checkbuttons
        self.inner_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW, tags='filters')

        self.tags     = show_all_tags(connection)
        self.pdf_tags = show_pdf_tags(connection, pdf_id)
        self.colors   = ['white', '#d9cf9a']
        self.values   = []
        self.buttons  = []
        for i, tag in enumerate(self.tags):
            filter_button = tk.Button(self.inner_frame, text=tag, bg=self.colors[int(tag in self.pdf_tags)], fg='black',
                                      padx=10, command=lambda b=i: self.filter_button_click(b), font=('Arial',14), anchor='w')
            filter_button.pack(fill=tk.X)
            self.buttons.append(filter_button)
            self.values.append(int(tag in self.pdf_tags))     

        self.update_canvas_scroll_region(None)

    def filter_button_click(self, idx):
        tag_text = self.buttons[idx].cget('text')
        tag_id   = get_tag_id(connection, tag_text)
        if self.values[idx] == 1:
            delete_pdf_tag(connection, self.pdf_id, tag_id)
        else:
            assign_pdf_tag(connection, self.pdf_id, tag_id)
        
        self.values[idx] = (self.values[idx] + 1) % 2
        self.buttons[idx].configure(bg=self.colors[self.values[idx]])

    def confirm_tags(self):
        menu_frame.all_files_command()
        self.destroy()

    def update_canvas_scroll_region(self, event):
        # Update the canvas scroll region to match the inner frame's size
        self.inner_frame.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def update_window_size(self, event):
        self.canvas.itemconfig('filters', width=self.canvas.winfo_width())



class AddQueueDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('Add queue')
        self.iconphoto(True, tk.PhotoImage(file=get_resource_path('images\\q_logo.png')))

        self.entry_label = tk.Label(self, text="Enter the name for the new queue:")
        self.entry_label.pack(pady=5)
        self.entry = tk.Entry(self)
        self.entry.pack(ipadx=5, ipady=5)
        self.ok_button = tk.Button(self, text="OK", command=self.on_ok)
        self.ok_button.pack(pady=5)

    def on_ok(self):
        self.result = self.entry.get()
        self.destroy()

class AddNoteDialog(simpledialog.Dialog):
    def __init__(self, parent):
        self.icon       = get_resource_path('images\\q_logo.png')
        self.title_text = 'Add note'
        super().__init__(parent)

    def body(self, master):
        tk.Label(master, text="Enter the new note:").grid(row=0, column=0)
        self.note_entry = tk.Text(master, height=10, width=40, font=('Arial', 12))
        self.note_entry.grid(row=1, column=0)
        return self.note_entry

    def apply(self):
        self.result = self.note_entry.get("1.0", "end-1c").rstrip('\n')

class EditNoteDialog(simpledialog.Dialog):
    def __init__(self, parent, old_note):
        self.old_note   = old_note
        self.icon       = get_resource_path('images\\q_logo.png')
        self.title_text = 'Edit note'
        super().__init__(parent)
    
    def body(self, master):
        tk.Label(master, text="Edit the note:").grid(row=0, column=0)
        self.note_entry = tk.Text(master, height=10, width=40, font=('Arial', 12))
        self.note_entry.grid(row=1, column=0)
        self.note_entry.insert('1.0', self.old_note)
        return self.note_entry
    
    def apply(self):
        self.result = self.note_entry.get("1.0", "end-1c").rstrip('\n')

    def set_icon_and_title(self):
        self.iconphoto(True, tk.PhotoImage(file=self.icon))
        self.title(self.title_text)


class EditMetadataDialog(tk.Toplevel):
    def __init__(self, parent, pdf_id):
        super().__init__(parent)
        self.title("Edit metadata")
        self.iconphoto(False, tk.PhotoImage(file=get_resource_path('images\\q_logo.png')))
        
        self.pdf_id = pdf_id
        current_values = show_pdf(connection, self.pdf_id)
        field_names = ['title', 'authors', 'journal', 'year', 'doi', 'path']
        
        self.entries = {}
        row_idx = 0
        for field_name, current_value in zip(field_names, current_values):
            label = tk.Label(self, text=field_name.title() + ":", font=('Arial', 12))
            label.grid(row=row_idx, column=0, sticky="e", padx=5, pady=5)
            entry = tk.Text(self, font=('Arial', 12), width=75, height=3, wrap=tk.WORD)
            entry.insert(tk.END, current_value)
            entry.grid(row=row_idx, column=1, padx=10, pady=5)
            self.entries[field_name] = entry
            row_idx += 1
        
        confirm_button = tk.Button(self, text="OK", font=('Arial', 12), command=self.confirm_changes)
        confirm_button.grid(row=row_idx, columnspan=2, pady=10)
    
    def confirm_changes(self):
        new_values = {field_name: entry.get("1.0", tk.END).strip() for field_name, entry in self.entries.items()}
        for column, new_value in new_values.items():
            update_pdf(connection, column, new_value, self.pdf_id)
        menu_frame.all_files_command()
        self.destroy()

class EditPathDialog(tk.Toplevel):
    
    def __init__(self, parent, pdf_id, table_name):
        super().__init__(parent)
        self.title("Edit file path")
        self.iconphoto(False, tk.PhotoImage(file=get_resource_path('images\\q_logo.png')))
        
        self.pdf_id = pdf_id
        self.table_name = table_name
        current_path = show_pdf(connection, self.pdf_id)[-1]
        
        label = tk.Label(self, text='Path' + ":", font=('Arial', 12))
        label.grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.entry = tk.Text(self, font=('Arial', 12), width=75, height=3, wrap=tk.WORD)
        self.entry.insert(tk.END, current_path)
        self.entry.grid(row=0, column=1, padx=5, pady=5)
        
        confirm_button = tk.Button(self, text="OK", font=('Arial', 12), command=self.confirm_changes)
        confirm_button.grid(row=1, columnspan=2, pady=10)
        
    def confirm_changes(self):
        new_value = self.entry.get("1.0", tk.END).strip()
        update_pdf(connection, 'path', new_value, self.pdf_id)
        menu_frame.display_table(self.table_name)
        self.destroy()


class NotesViewer(tk.Frame):

    def __init__(self, master, data=None):
        super().__init__(master)

        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure('TNotebook.Tab', background='#a3a3a3', font=('Arial', 13))

        self.current_data = data
        self.current_note_id = 0
        
        self.canvas_frame = ttk.Frame(self, style="TFrame")
        self.canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.notes_canvas = tk.Canvas(self.canvas_frame, bg=first_color, highlightthickness=0)
        self.notes_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.notes_scrollbar = ttk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.notes_canvas.yview)
        self.notes_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.notes_canvas.configure(yscrollcommand=self.notes_scrollbar.set)
        self.notes_canvas.bind('<Configure>', self.update_window_size)
        
        self.notes_list_frame = tk.Frame(self.notes_canvas, bg=first_color, padx=3, pady=3)
        self.notes_list_frame.pack(fill=tk.BOTH, expand=True)
        self.notes_list_frame.bind('<Configure>', self.update_scroll_region)
        
        self.window_id = self.notes_canvas.create_window((0, 0), window=self.notes_list_frame, anchor='nw', tags='notes_list')

        self.display_notes()
        
        
    def update_scroll_region(self, event):
        self.notes_canvas.configure(scrollregion=self.notes_canvas.bbox("all"))
    
    def update_window_size(self, event):
        self.notes_canvas.itemconfig('notes_list', width=self.notes_canvas.winfo_width(), height=self.notes_list_frame.winfo_reqheight())
    
    def clear_notes(self):
        for widget in self.notes_list_frame.winfo_children():
            widget.destroy()

    def load_pdf_notes(self, title, authors, journal, year):
        self.current_data = [title, authors, journal, year]
        self.display_notes()
    
    def display_notes(self):
        
        self.clear_notes()
        
        pdf_notes = []
        
        total_height = 0
        
        if (self.current_data):
            pdf_id    = get_file_id(connection, *self.current_data)    
            pdf_notes = [note[0] for note in get_pdf_notes(connection, pdf_id)]        
            bg_color  = '#d9cf9a'
            fg_color  = 'black'

            add_note_button = tk.Button(self.notes_list_frame, text='Create new note', font=('Arial', 15),
                                        relief=tk.FLAT, overrelief=tk.FLAT, command=self.add_pdf_note)
            add_note_button.pack(fill=tk.X, padx=4, pady=4)
            total_height += add_note_button.winfo_reqheight() + 15
            
        if len(pdf_notes) == 0 or not os.path.exists(pdf_viewer_frame.pdf_path):

            pdf_notes = ['No notes to display']
            bg_color  = first_color
            fg_color  = 'white'
                
        for note in pdf_notes:
            label = tk.Label(self.notes_list_frame, text=note, font='arial 15', anchor='w', padx=10, pady=10, bg=bg_color, fg=fg_color, highlightbackground=first_color, highlightthickness=4, justify='left', wraplength=500) 
            label.pack(fill=tk.BOTH, expand=True)
            label.bind("<Button-3>", self.show_context_menu)            
        
            total_height += label.winfo_reqheight()
            self.notes_canvas.config(scrollregion=(0, 0, 0, total_height))
            self.notes_canvas.itemconfig(self.window_id, height=total_height)

    def show_context_menu(self, event):

        label_widget = event.widget
        note_text = label_widget.cget("text")

        pdf_id = get_file_id(connection, *self.current_data)
        
        self.current_note_id = get_note_id(connection, pdf_id, note_text)
        
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Edit note",   command=self.edit_pdf_note)
        self.context_menu.add_command(label="Delete note", command=self.delete_pdf_note)
        self.context_menu.post(event.x_root, event.y_root)

    def add_pdf_note(self):
        pdf_id = get_file_id(connection, *self.current_data)
        dialog = AddNoteDialog(self)
        new_note = dialog.result
        if new_note:
            add_note(connection, pdf_id, new_note)
        self.display_notes()

    def edit_pdf_note(self):
        old_note = get_note_text(connection, self.current_note_id)
        dialog = EditNoteDialog(self, old_note)
        if dialog.result:
            edit_note(connection, self.current_note_id, dialog.result)
        self.display_notes()

    def delete_pdf_note(self):        
        delete_note(connection, self.current_note_id)
        self.display_notes()



class PDFPreviewer(ttk.Frame):
    
    def __init__(self, master, current_pdf_path=''):
        super().__init__(master, style="TFrame")

        self.pdf_path = current_pdf_path
        self.current_page = 1
        self.current_image = None

        canvas_frame = tk.Frame(self, bg='blue', highlightthickness=0)
        canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg="red", width=notebook_frame.winfo_width())
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        previous_button = tk.Button(canvas_frame, text="◀", command=self.previous_page, height=2)
        next_button     = tk.Button(canvas_frame, text="▶", command=self.next_page,     height=2)

        previous_button.pack(side=tk.LEFT,  fill=tk.X, padx=0, expand=True)
        next_button    .pack(side=tk.RIGHT, fill=tk.X, padx=0, expand=True)

        self.load_page()

    def load_new_pdf(self, pdf_path):
        self.pdf_path = pdf_path
        self.current_page = 1
        self.load_page()

    def clear_page(self):
        for widget in self.canvas.winfo_children():
            widget.destroy()
        if self.current_image:
            self.canvas.delete(self.current_image)
        self.canvas.config(bg='white')

    def change_path(self):
        pdf_id = get_file_id_from_path(connection, self.pdf_path)
        new_path = filedialog.askopenfilename(initialdir = "/",title = "Select file",filetypes = (("pdf files","*.pdf"),("all files","*.*")))
        if new_path:
            if os.path.exists(new_path):
                update_pdf(connection, 'path', new_path, pdf_id)
                menu_frame.all_files_command()

    def delete_file(self):
        confirm = tk.messagebox.askyesno(title='Confirmation', 
                                         message='Are you sure you want to delete the file?')
        if confirm:
            pdf_id = get_file_id_from_path(connection, self.pdf_path)
            delete_pdf(connection, pdf_id)
            menu_frame.all_files_command()

    def load_page(self, rendering_options=None):
        self.clear_page()
        
        if self.pdf_path:
            if os.path.exists(self.pdf_path):   
                pdf_document       = fitz.open(self.pdf_path)
                page               = pdf_document.load_page(self.current_page - 1)
                image              = page.get_pixmap(matrix=rendering_options, alpha=False)
                img                = Image.frombytes('RGB', (image.width, image.height), image.samples)
                photo              = ImageTk.PhotoImage(img)
                self.current_image = self.canvas.create_image(0, 0, anchor=tk.NW, image=photo)
                self.canvas.photo  = photo
                pdf_document.close()
                self.focus_set()
            else:
                self.canvas.config(bg=first_color)
                head_label  = tk.Label(self.canvas, text='Invalid directory', font=('Arial', 18), bg=first_color, fg='white')
                small_label = tk.Label(self.canvas, text='The document must have been moved or deleted.\nProvide its current path or remove it from the application.', font=('Arial', 13), bg=first_color, fg='white', padx=10, pady=10)
                change_path_button = tk.Button(self.canvas, text='Change path', font=('Arial', 15), command=self.change_path, bg="white", width=15, height=2)
                delete_file_button = tk.Button(self.canvas, text='Delete file', font=('Arial', 15), command=self.delete_file, bg="white", width=15, height=2)
                head_label .pack(side=tk.TOP, anchor=tk.CENTER, pady=20)
                small_label.pack(side=tk.TOP, anchor=tk.CENTER, pady=10)
                change_path_button.pack(side=tk.TOP, anchor=tk.CENTER, pady=0)
                delete_file_button.pack(side=tk.TOP, anchor=tk.CENTER, pady=10)
        else:
            label = tk.Label(self.canvas, text="No document selected", font='arial 15', bg=first_color, fg='white', padx=10, pady=10)
            label.pack(fill=tk.BOTH, expand=True)
    
        
    def previous_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_page(rendering_options={"antialias": True})
    
    def next_page(self):
        pdf_document = fitz.open(self.pdf_path)
        total_pages = pdf_document.page_count
        pdf_document.close()

        if self.current_page < total_pages:
            self.current_page += 1
            self.load_page(rendering_options={"antialias": True})

    def external_viewer(self):
        sp.Popen([self.pdf_path], shell=True)



class CustomTableRow(tk.Frame):
    def __init__(self, master, data, all_rows):
        super().__init__(master)
        
        self.data     = list(data)
        self.pdf_id   = get_file_id(connection, *self.data[:-1])
        self.all_rows = all_rows
        self.colors_dict = {'To be read': 'red', 'Being read': 'orange', 'Already read': 'green'}

        self.tags = self.get_tags_string()
        
        self.row_frame = tk.Frame(self, bd=0, relief="solid", bg="lightgray")
        self.row_frame.pack(fill="both", expand=True)
        
        self.title_label        = tk.Label(self.row_frame, text=self.data[0],                      font=('Arial', 14, 'bold'),   anchor='w', bg="lightgray", wraplength=550, justify='left')
        self.authors_label      = tk.Label(self.row_frame, text=self.data[1],                      font=('Arial', 11, 'italic'), anchor='w', bg="lightgray", wraplength=550, justify='left')
        self.year_journal_label = tk.Label(self.row_frame, text=f"{self.data[3]}, {self.data[2]}", font=('Arial', 11),           anchor='w', bg="lightgray", wraplength=550, justify='left')
        self.tags_label         = tk.Label(self.row_frame, text=f'Tags: {self.tags}',              font=('Arial', 11, 'bold'),   anchor='w', bg='lightgray', wraplength=550, justify='left')
        self.label_label        = tk.Label(self.row_frame, text=self.data[4],                      font=('Arial', 12, 'bold'),   anchor='w', bg='lightgray', wraplength=550, justify='left', fg=self.colors_dict[self.data[4]])
        
        self.title_label       .pack(side=tk.TOP, fill=tk.X, pady=4, padx=7)
        self.authors_label     .pack(side=tk.TOP, fill=tk.X, pady=1, padx=7)
        self.year_journal_label.pack(side=tk.TOP, fill=tk.X, pady=1, padx=7)
        self.tags_label        .pack(side=tk.TOP, fill=tk.X, pady=1, padx=7)
        self.label_label       .pack(side=tk.TOP, fill=tk.X, pady=1, padx=7)
        
        self.title_label       .bind("<Button-1>", self.on_click)
        self.authors_label     .bind("<Button-1>", self.on_click)
        self.year_journal_label.bind("<Button-1>", self.on_click)
        self.row_frame         .bind("<Button-1>", self.on_click)
        self.tags_label        .bind("<Button-1>", self.on_click)
        self.label_label       .bind("<Button-1>", self.change_label)
        
        self.title_label       .bind("<Button-3>", self.show_context_menu)
        self.authors_label     .bind("<Button-3>", self.show_context_menu)
        self.year_journal_label.bind("<Button-3>", self.show_context_menu)
        self.row_frame         .bind("<Button-3>", self.show_context_menu)
        self.tags_label        .bind("<Button-3>", self.show_context_menu)
        self.label_label       .bind("<Button-3>", self.show_context_menu)
        
        self.currently_clicked_frame = None   

    def get_tags_string(self):
        tags = show_pdf_tags(connection, self.pdf_id)
        tags_string = ''
        for idx, tag in enumerate(tags):
            if idx == 0:
                tags_string += tag
            else:
                tags_string += f', {tag}'
        if tags_string == '':
            tags_string = '-'
        return tags_string

    def update_metadata(self, new_data):
        self.data = new_data
        
        self.title_label.config(text=new_data[0])
        self.authors_label.config(text=new_data[1])
        self.year_journal_label.config(text=f"{new_data[3]}, {new_data[2]}")

    def on_click(self, event):
        parent_frame = self.row_frame
        
        for row in self.all_rows:
            if row != self:
                row.unhighlight_frame(row.row_frame)
        
        # Unhighlight the previously clicked frame
        if self.currently_clicked_frame:
            self.unhighlight_frame(self.currently_clicked_frame)
        
        # Highlight the clicked frame
        self.highlight_frame(parent_frame)
        
        # Update the currently clicked frame
        self.currently_clicked_frame = parent_frame
        
        pdf_file_path = get_file_path(connection, *self.data[:-1])
        pdf_viewer_frame.load_new_pdf(pdf_file_path)

        notes_viewer_frame.load_pdf_notes(*self.data[:-1])

    def change_label(self, event):
        pdf_id              = get_file_id(connection, *self.data[:-1])
        current_label       = self.label_label['text']
        all_labels          = list(self.colors_dict.keys())
        current_label_index = all_labels.index(current_label)
        new_label_index     = (current_label_index + 1) % 3
        new_label           = all_labels[new_label_index]
        
        edit_pdf_label(connection, pdf_id, new_label)
        self.label_label.config(text=new_label, fg=self.colors_dict[new_label])
        root.update()


    
    def highlight_frame(self, frame):
        # Change the background color of all labels and row frame to highlight
        frame.config(bg="white")  # Change background color to highlight
        for child in frame.winfo_children():
            child.config(bg="white")  # Change background color to highlight
    
    def unhighlight_frame(self, frame):
        # Change the background color of all labels and row frame to their default color
        frame.config(bg="lightgray")  # Change background color to default
        for child in frame.winfo_children():
            child.config(bg="lightgray")  # Change background color to default


    def move_to_archive(self):
        queues = show_queues(connection)  
        
        for queue in queues:
            q_id = get_queue_id(connection, queue[1])
            delete_from_queue(connection, q_id, self.pdf_id)        
        
        add_to_archive(connection, 0, self.pdf_id)
        menu_frame.all_files_command()
        
    def add_pdf_to_queue(self):

        def add_to_selected_queue(selected_queue):
            queue_id       = get_queue_id(connection, selected_queue)
            existing_files = show_queue_files(connection, queue_id)
            if self.pdf_id in existing_files:
                info_label.configure(text='This file is already added to this queue', fg='red')
            else:
                pdf_to_queue(connection, queue_id, self.pdf_id)
                info_label.configure(text='File added succesfully', fg='green')

        queue_names = [queue[1] for queue in show_queues(connection)]

        x = (screen_width  - 300) // 2
        y = (screen_height - 150) // 2
        
        # Create a dialog window
        dialog = tk.Toplevel()
        dialog.geometry(f'300x200+{x}+{y}')
        dialog.title("Select Queue")
        
        # Label for the drop-down menu
        select_label = tk.Label(dialog, text="Select queue:", font=('Arial', 12))
        select_label.pack(pady=5)
        
        # Drop-down menu for selecting the queue
        selected_queue = tk.StringVar(dialog)
        selected_queue.set(queue_names[0])  # Set default value
        
        # Create the drop-down menu
        queue_dropdown = ttk.Combobox(dialog, font=('Arial', 15), textvariable=selected_queue, values=queue_names, state="readonly")
        queue_dropdown.pack(pady=5, padx=10)
        
        # Button to confirm selection
        confirm_button = tk.Button(dialog, text="Add to Queue", font=('Arial', 13), command=lambda: add_to_selected_queue(selected_queue.get()))
        confirm_button.pack(pady=5)

        info_label = tk.Label(dialog, text='', font=('Arial', 12))
        info_label.pack(pady=5)
        
        # Run the dialog window
        dialog.mainloop()
    

    def edit_pdf_metadata(self):
        edit_dialog = EditMetadataDialog(self, self.pdf_id)

    def assign_tags_to_pdf(self):
        assign_dialog = AssignTagsWindow(self, self.pdf_id)
    
    def show_context_menu(self, event):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Move to archive", command=self.move_to_archive)
        self.context_menu.add_command(label="Add to queue",    command=self.add_pdf_to_queue)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Edit metadata",   command=self.edit_pdf_metadata)
        self.context_menu.add_command(label="Assign tags",     command=self.assign_tags_to_pdf)
        self.context_menu.post(event.x_root, event.y_root)



class CustomQueueRow(tk.Frame):
    def __init__(self, master, data, all_rows, queue_name):
        super().__init__(master)
        
        # Store data
        self.queue_name  = queue_name
        self.data        = data
        self.pdf_id      = get_file_id(connection, *self.data[1:-1])
        self.all_rows    = all_rows
        self.colors_dict = {'To be read': 'red', 'Being read': 'orange', 'Already read': 'green'}
        self.tags = self.get_tags_string()

        self.row_frame = tk.Frame(self, bd=0, relief="solid", bg="lightgray")  # Set background color here
        self.row_frame.pack(fill="both", expand=True)

        # Create labels for each field inside the frame
        self.position_label     = tk.Label(self.row_frame, text=f'{self.data[0]}. ',               font=('Arial', 14, 'bold'),   anchor='w', bg="lightgray")
        self.title_label        = tk.Label(self.row_frame, text=self.data[1],                      font=('Arial', 14, 'bold'),   anchor='w', bg="lightgray", wraplength=500, justify='left')
        self.authors_label      = tk.Label(self.row_frame, text=self.data[2],                      font=('Arial', 11, 'italic'), anchor='w', bg="lightgray", wraplength=500, justify='left')
        self.year_journal_label = tk.Label(self.row_frame, text=f"{self.data[4]}, {self.data[3]}", font=('Arial', 11),           anchor='w', bg="lightgray", wraplength=500, justify='left')  
        self.tags_label         = tk.Label(self.row_frame, text=f'Tags: {self.tags}',              font=('Arial', 11, 'bold'),   anchor='w', bg='lightgray', wraplength=550, justify='left')
        self.label_label        = tk.Label(self.row_frame, text=self.data[5],                      font=('Arial', 12, 'bold'),   anchor='w', bg="lightgray", fg=self.colors_dict[self.data[5]])

        self.position_label    .pack(side=tk.LEFT, fill=tk.X, pady=3, padx=7, anchor='nw')
        self.title_label       .pack(side=tk.TOP,  fill=tk.X, pady=3, padx=0)
        self.authors_label     .pack(side=tk.TOP,  fill=tk.X, pady=1, padx=0)
        self.year_journal_label.pack(side=tk.TOP,  fill=tk.X, pady=1, padx=0)
        self.tags_label        .pack(side=tk.TOP,  fill=tk.X, pady=1, padx=0)
        self.label_label       .pack(side=tk.TOP,  fill=tk.X, pady=1, padx=0)
        
        
        # Bind click event to each label and the row frame
        self.title_label       .bind("<Button-1>", self.on_click)
        self.authors_label     .bind("<Button-1>", self.on_click)
        self.year_journal_label.bind("<Button-1>", self.on_click)
        self.label_label       .bind("<Button-1>", self.change_label)
        self.tags_label        .bind("<Button-1>", self.on_click)
        self.position_label    .bind("<Button-1>", self.on_click)
        self.row_frame         .bind("<Button-1>", self.on_click)

        self.title_label       .bind("<Button-3>", self.show_context_menu)
        self.authors_label     .bind("<Button-3>", self.show_context_menu)
        self.year_journal_label.bind("<Button-3>", self.show_context_menu)
        self.label_label       .bind("<Button-3>", self.show_context_menu)
        self.tags_label        .bind("<Button-3>", self.show_context_menu)
        self.position_label    .bind("<Button-3>", self.show_context_menu)
        self.row_frame         .bind("<Button-3>", self.show_context_menu)
        
        # Keep track of the currently clicked frame
        self.currently_clicked_frame = None
        
    def get_tags_string(self):
        tags = show_pdf_tags(connection, self.pdf_id)
        tags_string = ''
        for idx, tag in enumerate(tags):
            if idx == 0:
                tags_string += tag
            else:
                tags_string += f', {tag}'
        if tags_string == '':
            tags_string = '-'
        return tags_string
    
    def on_click(self, event):
        # Identify the parent frame (row frame)
        parent_frame = self.row_frame
        
        # Unhighlight all other rows
        for row in self.all_rows:
            if row != self:
                row.unhighlight_frame(row.row_frame)
        
        # Unhighlight the previously clicked frame
        if self.currently_clicked_frame:
            self.unhighlight_frame(self.currently_clicked_frame)
        
        # Highlight the clicked frame
        self.highlight_frame(parent_frame)
        
        # Update the currently clicked frame
        self.currently_clicked_frame = parent_frame
        
        pdf_file_path = get_file_path(connection, *self.data[1:-1])
        pdf_viewer_frame.load_new_pdf(pdf_file_path)

        notes_viewer_frame.load_pdf_notes(*self.data[1:-1])

    
    def highlight_frame(self, frame):
        # Change the background color of all labels and row frame to highlight
        frame.config(bg='white') 
        for child in frame.winfo_children():
            child.config(bg='white') 
            
    def unhighlight_frame(self, frame):
        # Change the background color of all labels and row frame to their default color
        frame.config(bg='lightgray')
        for child in frame.winfo_children():
            child.config(bg='lightgray')

    def change_label(self, event):
        current_label       = self.label_label['text']
        all_labels          = list(self.colors_dict.keys())
        current_label_index = all_labels.index(current_label)
        new_label_index     = (current_label_index + 1) % 3
        new_label           = all_labels[new_label_index]
        
        edit_pdf_label(connection, self.pdf_id, new_label)
        self.label_label.config(text=new_label, fg=self.colors_dict[new_label])
        root.update()

    def remove_from_queue(self):
        queue_id = get_queue_id(connection, self.queue_name)    
        delete_from_queue(connection, queue_id, self.pdf_id)
        menu_frame.display_table(self.queue_name)
        
    def move_to_archive(self):
        queues   = show_queues(connection)
        queue_id = get_queue_id(connection, self.queue_name)
        
        for queue in queues:
            q_id = get_queue_id(connection, queue[1])
            delete_from_queue(connection, q_id, self.pdf_id)
        
        add_to_archive(connection, queue_id, self.pdf_id)
        menu_frame.display_table(self.queue_name)

    def change_position(self):
        queue_id     = get_queue_id(connection, self.queue_name)
        new_position = tk.simpledialog.askstring("Set new position", "Enter the new position number:")
        if new_position:
            edit_position(connection, queue_id, self.pdf_id, int(new_position))
            menu_frame.display_table(self.queue_name)

    def move_up(self):
        queue_id         = get_queue_id(connection, self.queue_name)
        current_position = get_file_position(connection, self.queue_name, self.pdf_id)
        edit_position(connection, queue_id, self.pdf_id, current_position-1)
        menu_frame.display_table(self.queue_name)
        
    def move_down(self):
        queue_id         = get_queue_id(connection, self.queue_name)
        current_position = get_file_position(connection, self.queue_name, self.pdf_id)
        edit_position(connection, queue_id, self.pdf_id, current_position+1)
        menu_frame.display_table(self.queue_name)

    def edit_pdf_metadata(self):
        edit_dialog = EditMetadataDialog(self, self.pdf_id, self.queue_name)

    def assign_tags_to_pdf(self):
        assign_dialog = AssignTagsWindow(self, self.pdf_id)
    
    def show_context_menu(self, event):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Move to archive",   command=self.move_to_archive)
        self.context_menu.add_command(label="Remove from queue", command=self.remove_from_queue)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Move up",           command=self.move_up)
        self.context_menu.add_command(label="Move down",         command=self.move_down)
        self.context_menu.add_command(label="Set new position",  command=self.change_position)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Edit metadata",  command=self.edit_pdf_metadata)
        self.context_menu.add_command(label="Assign tags",     command=self.assign_tags_to_pdf)
        self.context_menu.post(event.x_root, event.y_root)



class CustomArchiveRow(tk.Frame):
    def __init__(self, master, data, all_rows):
        super().__init__(master)
        
        # Store data
        self.data     = data
        self.all_rows = all_rows  # Store all rows
        
        # Create a frame to contain all labels
        self.row_frame = tk.Frame(self, bd=0, relief="solid", bg="lightgray")  # Set background color here
        self.row_frame.pack(fill="both", expand=True)
        
        # Create labels for each field inside the frame
        self.title_label        = tk.Label(self.row_frame, text=self.data[0],                      font=('Arial', 15, 'bold'),   anchor='w', bg="lightgray", wraplength=550, justify='left')  # Set background color here
        self.authors_label      = tk.Label(self.row_frame, text=self.data[1],                      font=('Arial', 12, 'italic'), anchor='w', bg="lightgray", wraplength=550, justify='left')  # Set background color here
        self.year_journal_label = tk.Label(self.row_frame, text=f"{self.data[3]}, {self.data[2]}", font=('Arial', 12),           anchor='w', bg="lightgray", wraplength=550, justify='left')  # Set background color here
        
        self.title_label       .pack(side=tk.TOP, fill=tk.X, pady=5, padx=7)
        self.authors_label     .pack(side=tk.TOP, fill=tk.X, pady=3, padx=7)
        self.year_journal_label.pack(side=tk.TOP, fill=tk.X, pady=3, padx=7)
        
        
        # Bind click event to each label and the row frame
        self.title_label       .bind("<Button-1>", self.on_click)
        self.authors_label     .bind("<Button-1>", self.on_click)
        self.year_journal_label.bind("<Button-1>", self.on_click)
        self.row_frame         .bind("<Button-1>", self.on_click)

        self.title_label       .bind("<Button-3>", self.show_context_menu)
        self.authors_label     .bind("<Button-3>", self.show_context_menu)
        self.year_journal_label.bind("<Button-3>", self.show_context_menu)
        self.row_frame         .bind("<Button-3>", self.show_context_menu)
              
        # Keep track of the currently clicked frame
        self.currently_clicked_frame = None

    def on_click(self, event):
        parent_frame = self.row_frame
        
        for row in self.all_rows:
            if row != self:
                row.unhighlight_frame(row.row_frame)
        
        if self.currently_clicked_frame:
            self.unhighlight_frame(self.currently_clicked_frame)
        
        self.highlight_frame(parent_frame)
        self.currently_clicked_frame = parent_frame
        
        pdf_file_path = get_file_path(connection, *self.data)
        pdf_viewer_frame.load_new_pdf(pdf_file_path)

        notes_viewer_frame.load_pdf_notes(*self.data)

    
    def highlight_frame(self, frame):
        frame.config(bg="white")
        for child in frame.winfo_children():
            child.config(bg="white")
    
    def unhighlight_frame(self, frame):
        frame.config(bg="lightgray")
        for child in frame.winfo_children():
            child.config(bg="lightgray")
            
    def delete_file(self):

        confirm = tk.messagebox.askyesno(title='Confirmation', 
                                         message='Are you sure you want to delete the file?')
        if confirm:
            pdf_id = get_file_id(connection, *self.data)
            delete_pdf(connection, pdf_id)
            self.destroy()

    def restore_file(self):
        pdf_id = get_file_id(connection, *self.data)
        restore_pdf(connection, pdf_id)
        self.destroy()    

    def show_context_menu(self, event):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Delete file",  command=self.delete_file)
        self.context_menu.add_command(label="Restore file", command=self.restore_file)
        self.context_menu.post(event.x_root, event.y_root)




class ScrollableFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        
        # Create a canvas widget and a scrollbar
        self.canvas    = tk.Canvas(self, bg=first_color, bd=0, highlightthickness=0, relief='ridge')
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        # Create a frame to contain the content
        self.content_frame = tk.Frame(self.canvas, bg=first_color, bd=0)
        
        # Configure the canvas
        self.canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.content_frame_window = self.canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        
        # Pack the canvas and scrollbar
        self.canvas   .pack(side=tk.LEFT,  fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind events to update the scrollbar
        self.content_frame.bind("<Configure>", self.on_frame_configure)
        self.canvas       .bind("<Configure>", self.on_canvas_configure)
        
    def on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
    def on_canvas_configure(self, event):
        self.canvas.itemconfig(self.content_frame_window, width=event.width)


class MenuFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        
        self.sorting = 'Date'
        self.order   = 'DESC'
        self.filters = []

        self.menu_canvas = tk.Canvas(self, bg=first_color, highlightthickness=0, width=screen_width*0.15)
        self.menu_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.menu_scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.menu_canvas.yview)
        self.menu_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.menu_canvas.configure(yscrollcommand=self.menu_scrollbar.set)
        self.menu_canvas.bind('<Configure>', self.update_window_size)
        
        self.buttons_frame = tk.Frame(self.menu_canvas, bg=first_color, padx=3, pady=3)
        self.buttons_frame.pack(fill=tk.BOTH, expand=True)
        self.buttons_frame.bind('<Configure>', self.update_scroll_region)
        
        self.window_id = self.menu_canvas.create_window((0, 0), window=self.buttons_frame, anchor='nw', tags='buttons_list')
        ### Menu buttons ###
        self.button_all_files = tk.Button(self.buttons_frame, text="All Files", padx=10, bg=first_color, fg='white', 
                                          command=self.all_files_command, bd=0, font=('Arial', 18), anchor='w', relief=tk.SUNKEN, 
                                          overrelief=tk.SUNKEN)
        self.button_archive   = tk.Button(self.buttons_frame, text="Archive",   padx=10, bg=first_color, fg='white', 
                                          command=self.archive_command,   bd=0, font=('Arial', 18), anchor='w', relief=tk.SUNKEN, 
                                          overrelief=tk.SUNKEN)
        self.label_queues = tk.Label(self.buttons_frame, text="Queues", padx=10, bg=first_color, fg='white', font=('Arial', 18), anchor='w')

        # Queues
        self.queues_list = show_queues(connection)
        self.queue_buttons = [tk.Button(self.buttons_frame,
                                         text=queue[1],
                                         bg=first_color,
                                         fg='white',
                                         command=lambda q=queue: self.queue_command(q[1]),
                                         bd=0,
                                         font=('Arial', 14),
                                         anchor='w',
                                         padx=20,
                                         relief=tk.SUNKEN,
                                         overrelief=tk.SUNKEN,
                                         wraplength=250,
                                         justify=tk.LEFT) for queue in self.queues_list]

        # Packing buttons and a label
        self.button_all_files.pack(fill=tk.X, padx=5, pady=5)
        self.button_archive  .pack(fill=tk.X, padx=5, pady=5)
        self.label_queues    .pack(fill=tk.X, padx=5, pady=5)

        # Dictionary to store button references #
        self.queue_buttons_dict = {queue[0]: button for queue, button in zip(self.queues_list, self.queue_buttons)}

        for queue_button in self.queue_buttons:
            queue_button.bind("<Button-3>", self.show_queue_context_menu)
            queue_button.pack(fill=tk.X, padx=5, pady=3)

        self.all_files_command()


    def update_scroll_region(self, event):
        self.menu_canvas.configure(scrollregion=self.menu_canvas.bbox("all"))
    
    def update_window_size(self, event):
        self.menu_canvas.itemconfig('buttons_list', width=self.menu_canvas.winfo_width(), height=self.buttons_frame.winfo_reqheight())
        
        
    # Function to clear the table
    def clear_table(self):
        global table_frame
        if table_frame:
            for widget in table_frame.winfo_children():
                widget.destroy()


    # Function to display the table
    def display_table(self, table_name):
        self.clear_table()
        
        # Create a ScrollableFrame to contain the custom rows
        scrollable_frame = ScrollableFrame(table_frame)
        scrollable_frame.pack(fill=tk.BOTH, expand=True)

        if self.sorting == 'Date':
            sorting = 'pdf_id'
        else:
            sorting = self.sorting
    
        # Load the table contents
        rows = show_table(connection, table_name, sorting, self.order)
      # Create custom rows and add them to the scrollable frame
        all_rows = []
        if table_name == 'pdf':
            for tag in self.filters:
                new_rows = []        
                for file_data in rows:
                    file_id   = get_file_id(connection, *file_data[:-1])
                    file_tags = show_pdf_tags(connection, file_id)
                    if tag in file_tags:
                        new_rows.append(file_data)
                rows = new_rows
            for row in rows:
                custom_table_row = CustomTableRow(scrollable_frame.content_frame, row, all_rows)
                custom_table_row.pack(side=tk.TOP, fill=tk.X, padx=7, pady=3)
                all_rows.append(custom_table_row)
        elif table_name == 'archive':
            for row in rows:
                custom_table_row = CustomArchiveRow(scrollable_frame.content_frame, row, all_rows)
                custom_table_row.pack(side=tk.TOP, fill=tk.X, padx=7, pady=3)
                all_rows.append(custom_table_row)
        else:
            for row in rows:
                custom_table_row = CustomQueueRow(scrollable_frame.content_frame, row, all_rows, table_name)
                custom_table_row.pack(side=tk.TOP, fill=tk.X, padx=7, pady=3)
                all_rows.append(custom_table_row)

    def all_files_command(self):
        self.update_button_state(self.button_all_files)
        self.clear_table()
        self.display_table('pdf')
    
    def archive_command(self):
        self.update_button_state(self.button_archive)
        self.clear_table()
        self.display_table('archive')
        
    def queue_command(self, queue_name):
        queues = show_queues(connection)
        queue_idx = get_queue_idx(connection, queue_name)
        self.update_button_state(self.queue_buttons_dict[queue_idx])
        self.display_table(queue_name)


    def update_button_state(self, clicked_button):
        # Reset colors for all buttons
        for button in [self.button_all_files, self.button_archive] + self.queue_buttons:
            button.config(bg=first_color, fg='white')
    
        # Change colors for the clicked button
        clicked_button.config(bg=clicked_color, fg='white')


    def show_queue_context_menu(self, event):
        queue_name = event.widget.cget('text').strip()
        context_menu = tk.Menu(root, tearoff=0)
        context_menu.add_command(label="Rename", command=lambda: self.rename_queue_dialog(queue_name))
        context_menu.add_command(label="Delete", command=lambda: self.delete_queue_context_menu(queue_name))
        context_menu.post(event.x_root, event.y_root)
    
    
    def rename_queue_dialog(self, queue_name):
        
        def rename_queue_function(new_queue_name):
            existing_queues = [queue[1] for queue in show_queues(connection)]
            if new_queue_name in existing_queues and new_queue_name != queue_name:
                info_label.configure(text='A queue with this name already exist', fg='red')
            else:
                rename_queue(connection, queue_name, new_queue_name)

                for q_button in self.queue_buttons:
                    if q_button['text'].strip() == queue_name:
                        q_button['text'] = new_queue_name
                        q_button.config(command=lambda q=new_queue_name: self.queue_command(q))

                self.update()
                dialog.destroy()
                    
        x = (screen_width  - 300) // 2
        y = (screen_height - 150) // 2
            
        # Create a dialog window
        dialog = tk.Toplevel()
        dialog.geometry(f'300x200+{x}+{y}')
        dialog.title("Rename queue")
            
        # Label for the drop-down menu
        select_label = tk.Label(dialog, text="Enter new queue name:", font=('Arial', 12))
        select_label.pack(pady=5)
            
        # Create the drop-down menu
        queue_entry = tk.Text(dialog, font=('Arial', 12), width=30, height=1)
        queue_entry.insert('1.0', queue_name)
        queue_entry.pack(pady=5, padx=10)
            
        # Button to confirm selection
        confirm_button = tk.Button(dialog, text="Rename queue", font=('Arial', 13), 
                                   command=lambda: rename_queue_function(queue_entry.get("1.0", tk.END).rstrip('\n')))
        confirm_button.pack(pady=5)
    
        info_label = tk.Label(dialog, text='', font=('Arial', 12))
        info_label.pack(pady=5)
            
        # Run the dialog window
        dialog.mainloop()
    
    
    def delete_queue_context_menu(self, queue_name):
        confirm = tk.messagebox.askyesno(title='Confirmation', 
                                         message=f'Are you sure you want to delete the queue \'{queue_name}\'?')
        if confirm:
            queues = show_queues(connection)
            if len(queues) > 1:
                queue_indices = [queue[0] for queue in queues]
                queue_idx     = get_queue_idx(connection, queue_name)
                if queue_idx == queue_indices[-1]:
                    queue_indices  = queue_indices[:-1]
                    previous_idx   = queue_indices[-1]
                    previous_queue = [queue for queue in queues if queue[0] == previous_idx][0][1]
                    self.queue_command(previous_queue)
                else:
                    next_idx   = queue_indices[queue_indices.index(queue_idx) + 1]
                    next_queue = [queue for queue in queues if queue[0] == next_idx][0][1]
                    self.queue_command(next_queue)
            else:
                self.all_files_command()
            for q_button in self.queue_buttons:
                if q_button['text'].strip() == queue_name:
                    q_button.pack_forget()
                    self.queue_buttons.remove(q_button)
            delete_queue(connection, queue_name)
            root.update()

       
    
    def add_queue_dialog(self):

        def add_new_queue(new_queue_name):
            existing_queues = [queue[1] for queue in show_queues(connection)]
            if new_queue_name in existing_queues:
                info_label.configure(text='A queue with this name already exist', fg='red')
            else:
                add_queue(connection, new_queue_name)
                info_label.configure(text='Queue added succesfully', fg='green')
                new_queue_button = tk.Button(self.buttons_frame,
                                             text=new_queue_name,
                                             bg=first_color,
                                             fg='white',
                                             command=lambda q=new_queue_name: self.queue_command(q),
                                             bd=0,
                                             font=('Arial', 14),
                                             anchor='w',
                                             padx=20,
                                             relief=tk.SUNKEN,
                                             overrelief=tk.SUNKEN,
                                             wraplength=250,
                                             justify=tk.LEFT)
                new_queue_button.bind("<Button-3>", self.show_queue_context_menu)
                new_queue_button.pack(fill=tk.X, pady=3, padx=5)
                self.update()
                    
                self.queue_buttons.append(new_queue_button)
            
                new_queue_idx = get_queue_idx(connection, new_queue_name)
                self.queue_buttons_dict[new_queue_idx] = new_queue_button

            self.update_window_size(None)
            self.update_scroll_region(None)
                
        x = (screen_width  - 300) // 2
        y = (screen_height - 150) // 2
            
        # Create a dialog window
        dialog = tk.Toplevel()
        dialog.geometry(f'300x200+{x}+{y}')
        dialog.title("Add queue")
            
        # Label for the drop-down menu
        select_label = tk.Label(dialog, text="Enter queue name:", font=('Arial', 12))
        select_label.pack(pady=5)
            
        # Create the drop-down menu
        queue_entry = tk.Text(dialog, font=('Arial', 12), width=30, height=1)
        queue_entry.pack(pady=5, padx=10)
            
        # Button to confirm selection
        confirm_button = tk.Button(dialog, text="Create queue", font=('Arial', 13), 
                                   command=lambda: add_new_queue(queue_entry.get("1.0", tk.END).rstrip('\n')))
        confirm_button.pack(pady=5)
    
        info_label = tk.Label(dialog, text='', font=('Arial', 12))
        info_label.pack(pady=5)
            
        # Run the dialog window
        dialog.mainloop()

class TopFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master)

        self.configure(bg=second_color)

        self.sorting_restored   = False
        self.filtering_restored = False

        ###   Top frame buttons   ###
        self.button_add_queue       = tk.Button(self, text="Add queue",               bg=second_color, fg='white', anchor = 'w', bd=0, command=menu_frame.add_queue_dialog,    font=('Arial', 12), relief=tk.SUNKEN, overrelief=tk.SUNKEN)
        self.button_add_document    = tk.Button(self, text="Add document",            bg=second_color, fg='white', anchor = 'w', bd=0, command=add_document_dialog, font=('Arial', 12), relief=tk.SUNKEN, overrelief=tk.SUNKEN)
        self.button_external_viewer = tk.Button(self, text="Open in external viewer", bg=second_color, fg='white', anchor = 'w', bd=0, command=pdf_viewer_frame.external_viewer,       font=('Arial', 12), relief=tk.SUNKEN, overrelief=tk.SUNKEN)
        self.button_tags            = tk.Button(self, text="Tag manager",             bg=second_color, fg='white', anchor = 'w', bd=0, command=self.show_tags_dialog,    font=('Arial', 12), relief=tk.SUNKEN, overrelief=tk.SUNKEN)        
        
        self.button_add_document   .pack(side=tk.LEFT, padx=10, pady=5)
        self.button_add_queue      .pack(side=tk.LEFT, padx=10, pady=5)
        self.button_external_viewer.pack(side=tk.LEFT, padx=10, pady=5)
        self.button_tags           .pack(side=tk.LEFT, padx=10, pady=5)

        self.selected_parameter = tk.StringVar(value='Date')

        self.tags = show_all_tags(connection)

        self.restore_sorting()
        self.restore_filtering()

    def show_filtering_dialog(self):
        supdialog = FilteringWindow(self)

    def show_tags_dialog(self):
        supdialog = TagManagerWindow(self)
    
    def restore_sorting(self):
        if not self.sorting_restored:
            self.label_sorting  = tk.Label( self, text='Sort documents', bg=second_color, fg='white', anchor='w',   bd=0, font=('Arial', 12))
            self.button_sorting = tk.Button(self, text="⯆",             bg=second_color, fg='red',   anchor = 'w', bd=0, font=('Arial', 12),
                                            command=self.change_order, relief=tk.SUNKEN, overrelief=tk.SUNKEN)
                
            self.menu_sorting = ttk.Combobox(self, state='readonly', values=['Date', 'Title', 'Authors', 'Journal', 'Year'], 
                                                 textvariable=self.selected_parameter)
            self.menu_sorting.bind('<<ComboboxSelected>>', self.set_sorting_parameter)
                
            self.menu_sorting  .pack(side=tk.RIGHT, padx=3, pady=5)
            self.button_sorting.pack(side=tk.RIGHT, padx=3, pady=5)
            self.label_sorting .pack(side=tk.RIGHT, padx=3, pady=5)
            self.restored = True
            self.update()

    def remove_sorting(self):
        if self.sorting_restored:
            self.label_sorting .destroy()
            self.menu_sorting  .destroy()
            self.button_sorting.destroy()
            self.restored = False
            self.update()

    def restore_filtering(self):
        if not self.filtering_restored:
            self.button_filtering = tk.Button(self, text='Filter documents', bg=second_color, fg='white', anchor='w', bd=0, font=('Arial', 12), 
                                              command=self.show_filtering_dialog)
            self.button_filtering.pack(side=tk.RIGHT, padx=30, pady=5)
            self.update()
            self.filtering_restored = True
    
    def remove_filtering(self):
        if self.filtering_restored:
            self.button_filtering.destroy()
            self.restored = False
            self.update()

    
    def change_order(self):
        if self.button_sorting.cget('text') == '⯆':
            self.button_sorting.configure(text='⯅', fg='green')
            menu_frame.order = 'ASC'
        else:
            self.button_sorting.configure(text='⯆', fg='red')
            menu_frame.order = 'DESC'
        self.update()
        menu_frame.all_files_command()

    def set_sorting_parameter(self, event):
        menu_frame.sorting = self.selected_parameter.get()
        menu_frame.all_files_command()


def add_document_dialog():
    file_path      = filedialog.askopenfilename(initialdir = "/",title = "Select file",filetypes = (("pdf files","*.pdf"),("all files","*.*")))
    if file_path:
        file_data      = get_metadata_from_pdf(file_path)
        pdf_data       = (file_data['title'], file_data['authors'], file_data['journal'], file_data['year'])
        existing_files = show_all_pdfs(connection)
        if pdf_data in existing_files:
            tk.messagebox.showerror(title='Info', message=f'File\n\n\'{pdf_data[0]}\'\n\nalready exists')
        else:
            tk.messagebox.showinfo(title='Info', message=f'File\n\n\'{pdf_data[0]}\'\n\nadded succesfully')
            add_pdf(connection, file_path)
            menu_frame.all_files_command()
    else:
        tk.messagebox.showerror(title='Info', message=f'The file cannot be added')


def on_drop(event):
    connection = connect_to_database()
    raw_file_paths = event.data
    file_paths = extract_paths(raw_file_paths)  # Assuming file paths are separated by newline characters
    for file_path in file_paths:
        if file_path:
            file_data      = get_metadata_from_pdf(file_path)
            pdf_data       = (file_data['title'], file_data['authors'], file_data['journal'], file_data['year'])
            existing_files = show_all_pdfs(connection)
            if pdf_data in existing_files:
                tk.messagebox.showerror(title='Info', message=f'File\n\n\'{pdf_data[0]}\'\n\nalready exists')
            else:
                tk.messagebox.showinfo(title='Info', message=f'File\n\n\'{pdf_data[0]}\'\n\nadded succesfully')
                add_pdf(connection, file_path)
                menu_frame.all_files_command()
        else:
            tk.messagebox.showerror(title='Info', message=f'The file cannot be added')
    connection.close()
    
    menu_frame.clear_table()
    menu_frame.display_table('pdf')
    menu_frame.update_button_state(menu_frame.button_all_files)
 


###   Application initialization   ###
root = TkinterDnD.Tk()
root.title('Q-Doc')
root.state('zoomed')
root.iconphoto(False, tk.PhotoImage(file=get_resource_path('images\\q_logo.png')))

screen_width  = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()

# Useful colors #
first_color   = '#292929'
second_color  = '#4a4a4a'
clicked_color = '#4a4a4a' 

windll.shcore.SetProcessDpiAwareness(1)


###   Table frame   ###
table_frame = tk.Frame(root, bg=first_color)

###   Notebook frame   ###
notebook_frame = ttk.Notebook(root)

# Preview tab #
preview_frame    = ttk.Frame(notebook_frame)
pdf_viewer_frame = PDFPreviewer(preview_frame)
pdf_viewer_frame.pack(fill=tk.BOTH, expand=True)
notebook_frame.add(preview_frame, text='Preview')

# Notes tab #
notes_frame  = tk.Frame(notebook_frame, bg=first_color)
notes_viewer_frame = NotesViewer(notes_frame)
notes_viewer_frame.pack(fill=tk.BOTH, expand=True)
notebook_frame.add(notes_frame, text='Notes')

###   Menu frame   ###
menu_frame = MenuFrame(root)

###   Top frame   ###
top_frame   = TopFrame(root)


###   Frames arrangement   ###
top_frame     .grid(row=0, columnspan=3, sticky='nsew')
menu_frame    .grid(row=1, column=0,     sticky='nsew')
table_frame   .grid(row=1, column=1,     sticky='nsew')
notebook_frame.grid(row=1, column=2,     sticky='nsew')

root.columnconfigure(0, weight=1)
root.columnconfigure(1, weight=3)
root.columnconfigure(2, weight=3)
root.rowconfigure(1, weight=1)

root.drop_target_register(DND_FILES)
root.dnd_bind('<<Drop>>', on_drop)


if __name__ == '__main__':
    
    menu_frame.display_table('pdf')
    menu_frame.update_button_state(menu_frame.button_all_files)
    
    root.mainloop()

connection.close()