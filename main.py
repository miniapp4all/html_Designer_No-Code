import sys, os, json, copy, zipfile, tempfile, shutil, urllib.parse, base64
from bs4 import BeautifulSoup, Tag, NavigableString
from PySide6.QtWidgets import (QApplication, QMainWindow, QSplitter, QWidget, 
                               QVBoxLayout, QHBoxLayout, QFormLayout, QTreeWidget, QTreeWidgetItem,
                               QLineEdit, QTextEdit, QPushButton, QMessageBox, QFileDialog, QLabel, QMenu, QSizePolicy,
                               QAbstractItemView, QColorDialog, QTabWidget, QGroupBox, QGridLayout, QComboBox, QCheckBox,
                                QListWidget) # <--- ADDED QListWidget HERE
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QUrl, Qt, QPoint, QRegularExpression
from PySide6.QtGui import QKeySequence, QShortcut, QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineContextMenuRequest, QWebEnginePage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class HTMLHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        tag_format = QTextCharFormat()
        tag_format.setForeground(QColor("#f44747"))
        self.rules.append((QRegularExpression(r'<[^>]*>'), tag_format))
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self.rules.append((QRegularExpression(r'"[^"]*"'), string_format))
        self.rules.append((QRegularExpression(r"'[^']*'"), string_format))

    def highlightBlock(self, text):
        for pattern, format in self.rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)

class DOMTreeWidget(QTreeWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def is_descendant(self, parent, child):
        curr = child.parent()
        while curr:
            if curr == parent: return True
            curr = curr.parent()
        return False
    def dropEvent(self, event):
        dragged_items = self.selectedItems()
        if not dragged_items: return super().dropEvent(event)
        dragged_item = dragged_items[0]
        target_item = self.itemAt(event.position().toPoint())
        drop_ind = self.dropIndicatorPosition()
        
        if not target_item or dragged_item == target_item or self.is_descendant(dragged_item, target_item):
            event.ignore(); return

        drag_tag = dragged_item.data(0, Qt.ItemDataRole.UserRole)
        target_tag = target_item.data(0, Qt.ItemDataRole.UserRole)

        if not drag_tag or not target_tag or drag_tag.name in ['body', 'html']:
            event.ignore(); return

        self.main_window.save_state_for_undo()
        drag_tag.extract()
        
        if drop_ind == QAbstractItemView.DropIndicatorPosition.OnItem: target_tag.append(drag_tag)
        elif drop_ind == QAbstractItemView.DropIndicatorPosition.AboveItem:
            if target_tag.name in ['body', 'html']: target_tag.append(drag_tag) 
            else: target_tag.insert_before(drag_tag)
        elif drop_ind == QAbstractItemView.DropIndicatorPosition.BelowItem:
            if target_tag.name in ['body', 'html']: target_tag.append(drag_tag)
            else: target_tag.insert_after(drag_tag)

        super().dropEvent(event)
        self.main_window.update_preview()
        self.main_window.statusBar().showMessage("🔄 Tag position changed and HTML updated!", 3000)

from PySide6.QtGui import QDesktopServices, QCursor
from PySide6.QtCore import QUrl

class CustomWebEnginePage(QWebEnginePage):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if isinstance(message, str):
            if message.startswith("EDITOR_SCROLL:"):
                try:
                    data = message.split("EDITOR_SCROLL:")[1]
                    x, y = data.split("|")
                    self.main_window.current_scroll_x = float(x)
                    self.main_window.current_scroll_y = float(y)
                except Exception:
                    pass
                    
            elif message.startswith("EDITOR_CLICK:"):
                self.main_window.select_tree_item_by_id(message.split("EDITOR_CLICK:")[1])
                # --- Return keyboard focus to the browser ---
                self.main_window.web_view.setFocus()
                
            elif message.startswith("EDITOR_EDIT_MODE:"):
                # Force focus again when the User is double-clicking to type
                self.main_window.web_view.setFocus()
                
            elif message.startswith("EDITOR_OPEN_LINK:"):
                url = message.split("EDITOR_OPEN_LINK:")[1]
                QDesktopServices.openUrl(QUrl(url))
            elif message.startswith("EDITOR_HINT:"):
                self.main_window.statusBar().showMessage(message.split("EDITOR_HINT:")[1], 4000)
            
            elif message.startswith("EDITOR_CONTEXT:"):
                eid = message.split("EDITOR_CONTEXT:")[1]
                self.main_window.select_tree_item_by_id(eid)
                self.main_window.web_view.setFocus() # Mandatory
                self.main_window.show_context_menu(QCursor.pos(), from_web=True)
            
            elif message.startswith("EDITOR_RESIZE:"):
                try:
                    data = message.split("EDITOR_RESIZE:")[1]
                    eid, w, h = data.split("|")
                    self.main_window.sync_resize_from_web(eid, w, h)
                except Exception as e:
                    pass
                    
            elif message.startswith("EDITOR_DRAG_POS:"):
                try:
                    data = message.split("EDITOR_DRAG_POS:")[1]
                    eid, left, top = data.split("|")
                    self.main_window.sync_drag_pos_from_web(eid, left, top)
                except Exception as e:
                    pass

        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

class PreviewWebEngineView(QWebEngineView):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setPage(CustomWebEnginePage(main_window, self))

    def contextMenuEvent(self, event):
        pass

from PySide6.QtWidgets import QScrollArea

class UniversalHTMLEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("html_Designer_LTH - No-Code Designer v5.2 (Ultimate Layout)")
        self.resize(1600, 950)
        self.soup = None; self.current_node = None; self.current_file_path = None
        self.clipboard_node = None; self.node_map = {}; self.undo_stack = [] 

        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #d4d4d4; font-family: 'Segoe UI', 'Consolas'; font-size: 13px; }
            QLineEdit, QTextEdit, QComboBox { background-color: #252526; border: 1px solid #3e3e42; padding: 6px; border-radius: 4px; }
            QTextEdit { font-size: 14px; line-height: 1.5; color: #4fc1ff; } 
            QPushButton { background-color: #0e639c; color: white; border-radius: 4px; font-weight: bold; padding: 8px; border: none; }
            QPushButton:hover { background-color: #1177bb; }
            QPushButton:disabled { background-color: #444444; color: #888888; }
            QTreeWidget { background-color: #252526; border: 1px solid #3e3e42; outline: none; }
            QTreeWidget::item { padding: 4px 6px; border-bottom: 1px solid #2d2d30; }
            QTreeWidget::item:selected { background-color: #094771; color: #ffffff; }
            QTabWidget::pane { border: 1px solid #3e3e42; border-radius: 4px; top: -1px; background-color: #252526; }
            QTabBar::tab { background: #2d2d30; color: #888; padding: 8px 20px; border: 1px solid #3e3e42; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
            QTabBar::tab:selected { background: #252526; color: #ffffff; font-weight: bold; border-top: 2px solid #007acc; }
            QGroupBox { border: 1px solid #3e3e42; border-radius: 6px; margin-top: 10px; padding-top: 15px; font-weight: bold; color: #ce9178; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            
            /* Customize the Splitter bar to make it extremely easy to grab and drag */
            QSplitter::handle { background-color: #3e3e42; }
            QSplitter::handle:horizontal { width: 4px; }
            QSplitter::handle:vertical { 
                height: 8px; 
                background-color: #252526; 
                border-top: 1px solid #3e3e42; 
                border-bottom: 1px solid #3e3e42; 
                margin: 2px 0;
            }
            QSplitter::handle:vertical:hover { background-color: #007acc; } /* Highlight blue on hover */
            
            /* Hide the border of the scroll area */
            QScrollArea { border: none; background-color: transparent; }
        """)

        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.undo_action)      

        self.tree = DOMTreeWidget(self) 
        self.tree.setHeaderHidden(True)
        
        for key, func in [("Ctrl+C", self.kbd_copy), ("Ctrl+V", self.kbd_paste), 
                          ("Ctrl+X", self.kbd_cut), ("Ctrl+D", self.kbd_duplicate),
                          (Qt.Key.Key_Delete, self.kbd_delete), (Qt.Key.Key_Backspace, self.kbd_delete)]:
            sc = QShortcut(QKeySequence(key), self.tree)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(func)
            
        # --- KEYBOARD SHORTCUTS TO INCREASE/DECREASE FONT SIZE LIKE WORD ---
        sc_inc_font = QShortcut(QKeySequence("Ctrl+]"), self)
        sc_inc_font.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_inc_font.activated.connect(lambda: self.kbd_adjust_font(2))

        sc_dec_font = QShortcut(QKeySequence("Ctrl+["), self)
        sc_dec_font.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_dec_font.activated.connect(lambda: self.kbd_adjust_font(-2))
        
        # --- SAVE SHORTCUT MUST BE SET AS "GLOBAL" (ApplicationShortcut) ---
        sc_save = QShortcut(QKeySequence("Ctrl+S"), self)
        sc_save.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_save.activated.connect(self.kbd_save)
        
        sc_save_as = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        sc_save_as.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_save_as.activated.connect(self.kbd_save_as)
        
        self.statusBar().showMessage("Ready - Undo (Ctrl+Z) & Save shortcut (Ctrl+S) enabled")
        
        self.statusBar().setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)


        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_layout.setSpacing(10)

        left_panel.setMinimumWidth(300)
       
        top_left_layout = QHBoxLayout(); top_left_layout.setContentsMargins(0,0,0,0)
        self.btn_open = QPushButton("📂 Open File"); self.btn_open.clicked.connect(self.load_file_dialog)
        
        self.btn_template = QPushButton("📑 HTML Template")
        self.btn_template.setStyleSheet("background-color: #d7ba7d; color: #1e1e1e; font-weight: bold;")
        self.btn_template.clicked.connect(self.show_template_gallery)

        self.inp_search_dom = QLineEdit(); self.inp_search_dom.setPlaceholderText("🔍 Quick tag search (Enter ID, Class...)")
        self.inp_search_dom.textChanged.connect(self.search_dom_tree)
        
        top_left_layout.addWidget(self.btn_open)
        top_left_layout.addWidget(self.btn_template) 
        top_left_layout.addWidget(self.inp_search_dom, stretch=1)
        left_layout.addLayout(top_left_layout)

        self.setup_quick_components_ui(left_layout)
        
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setChildrenCollapsible(False)
        left_layout.addWidget(left_splitter, stretch=1)

        # TOP PANEL (DOM Tree)
        tree_container = QWidget(); tree_layout = QVBoxLayout(tree_container); tree_layout.setContentsMargins(0,0,0,0)
        tree_container.setMinimumHeight(150)
        self.tree = DOMTreeWidget(self); self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(lambda item, col: self.on_item_clicked(item, col))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(lambda pos: self.show_context_menu(pos))
        tree_layout.addWidget(self.tree, stretch=1)

        self.lbl_breadcrumb = QLabel("📌 No tag selected")
        self.lbl_breadcrumb.setStyleSheet("background: #252526; padding: 8px; border: 1px solid #3e3e42; border-radius: 4px; color: #ce9178; font-weight: bold;")
        self.lbl_breadcrumb.setWordWrap(True)
        
        self.lbl_breadcrumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_breadcrumb.setMinimumHeight(35)
        self.lbl_breadcrumb.setMaximumHeight(70)
        
        tree_layout.addWidget(self.lbl_breadcrumb)
        left_splitter.addWidget(tree_container)

        bottom_container = QWidget(); bottom_layout = QVBoxLayout(bottom_container); bottom_layout.setContentsMargins(0,0,0,0)
        bottom_container.setMinimumHeight(150) # Allow it to be squeezed very small
        self.tabs = QTabWidget(); bottom_layout.addWidget(self.tabs, stretch=1)

        def make_scrollable(widget):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            return scroll

        self.inp_tag = QLineEdit(); self.inp_id = QLineEdit(); self.inp_class = QLineEdit(); self.inp_data_trang = QLineEdit()
        self.inp_href = QLineEdit(); self.inp_src = QLineEdit() 
        
        active_style = """
            QLineEdit, QComboBox { background-color: #252526; border: 1px solid #3e3e42; padding: 6px; border-radius: 4px; color: #d4d4d4; }
            QLineEdit:focus, QComboBox:focus, QLineEdit:hover:enabled { border: 1px solid #007acc; background-color: #2d2d30; color: #ffffff; font-weight: bold; }
            QLineEdit:disabled { background-color: #1a1a1a; border: 1px dashed #3e3e42; color: #555555; }
        """
        for w in [self.inp_tag, self.inp_id, self.inp_class, self.inp_data_trang, self.inp_href, self.inp_src]:
            w.setStyleSheet(active_style)

            if w != self.inp_tag: w.editingFinished.connect(self.apply_changes)
  
        self.inp_text = QWebEngineView()
        monaco_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <style> body, html { margin: 0; padding: 0; height: 100%; overflow: hidden; background-color: #1e1e1e; } #container { width: 100%; height: 100%; } </style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.38.0/min/vs/loader.min.js"></script>
        </head>
        <body>
            <div id="container"></div>
            <script>
                require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.38.0/min/vs' }});
                require(['vs/editor/editor.main'], function() {
                    window.editor = monaco.editor.create(document.getElementById('container'), {
                        value: '<!-- Select a tag to view the HTML code -->',
                        language: 'html',
                        theme: 'vs-dark',
                        wordWrap: 'on',
                        minimap: { enabled: false },
                        fontSize: 14,
                        automaticLayout: true
                    });
                });
            </script>
        </body>
        </html>
        """
        self.inp_text.setHtml(monaco_html)
        
        self.inp_style = QTextEdit(); self.inp_style.setAcceptRichText(False)
        self.inp_style.setStyleSheet("background-color: #1e1e1e; color: #d7ba7d; font-family: 'Consolas'; font-size: 14px; border: 1px solid #3e3e42;")
        
        self.inp_style.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.inp_style.setMinimumHeight(60)
        
        self.btn_bg_color = QPushButton("🎨 Fill Background"); self.btn_bg_color.clicked.connect(self.pick_bg_color)
        self.btn_text_color = QPushButton("🔤 Text Color"); self.btn_text_color.clicked.connect(self.pick_text_color)
        self.btn_browse_href = QPushButton("🔗"); self.btn_browse_href.clicked.connect(self.browse_href_file)
        self.btn_browse_src = QPushButton("🖼️"); self.btn_browse_src.clicked.connect(self.browse_src_file)
        for btn in [self.btn_browse_href, self.btn_browse_src]: btn.setFixedSize(30, 30)

        tab_config = QWidget(); form_config = QFormLayout(tab_config); form_config.setContentsMargins(15, 15, 15, 15)
        form_config.addRow("Tag Name:", self.inp_tag); form_config.addRow("ID:", self.inp_id)
        form_config.addRow("Class:", self.inp_class); form_config.addRow("Data-Page:", self.inp_data_trang)
        
        self.inp_form_action = QLineEdit(); self.inp_form_action.setPlaceholderText("Link API (VD: https://formspree.io/f/...)")
        self.inp_form_action.setStyleSheet(active_style); self.inp_form_action.editingFinished.connect(self.apply_changes)
        
        self.inp_form_method = QComboBox(); self.inp_form_method.addItems(["POST", "GET"]); self.inp_form_method.setStyleSheet(active_style)
        self.inp_form_method.currentTextChanged.connect(self.apply_changes)
        
        self.lbl_form = QLabel("Form Configuration:")
        self.lbl_form.setStyleSheet("color: #ff9800; font-weight: bold;")
        self.w_form = QWidget(); form_action_layout = QHBoxLayout(self.w_form); form_action_layout.setContentsMargins(0,0,0,0)
        form_action_layout.addWidget(self.inp_form_method)
        form_action_layout.addWidget(self.inp_form_action, stretch=1)
        form_config.addRow(self.lbl_form, self.w_form)
        self.lbl_form.setVisible(False); self.w_form.setVisible(False) # Hidden by default
        
        self.lbl_href = QLabel("Href (Link):")
        self.w_href = QWidget(); href_layout = QHBoxLayout(self.w_href); href_layout.setContentsMargins(0,0,0,0)
        href_layout.addWidget(self.inp_href)
        href_layout.addWidget(self.btn_browse_href)
        
        self.btn_make_link = QPushButton("🪄 Make Link")
        self.btn_make_link.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        self.btn_make_link.clicked.connect(self.convert_to_link)
        href_layout.addWidget(self.btn_make_link)
        form_config.addRow(self.lbl_href, self.w_href)
        
        # Wrap the Src block so it is fully hidden when the tag is not an Image
        self.lbl_src = QLabel("Src (Image):")
        self.w_src = QWidget(); src_layout = QHBoxLayout(self.w_src); src_layout.setContentsMargins(0,0,0,0)
        src_layout.addWidget(self.inp_src); src_layout.addWidget(self.btn_browse_src)
        form_config.addRow(self.lbl_src, self.w_src)
        
        self.chk_img_responsive = QCheckBox("🛡️ Force image to fit frame (Prevent breaking Layout)")
        self.chk_img_responsive.setStyleSheet("color: #28a745; font-weight: bold; margin-bottom: 5px;")
        form_config.addRow("", self.chk_img_responsive)
        self.tabs.addTab(make_scrollable(tab_config), "⚙️ Configuration")

        tab_style = QWidget(); style_layout = QVBoxLayout(tab_style); style_layout.setContentsMargins(15, 10, 15, 10)
        css_group = QGroupBox("📏 Size & Alignment"); css_grid = QGridLayout(css_group)
        self.css_width = QLineEdit(); self.css_width.setPlaceholderText("VD: 100px, 100%")
        self.css_height = QLineEdit(); self.css_height.setPlaceholderText("VD: 50px, auto")
        self.css_padding = QLineEdit(); self.css_padding.setPlaceholderText("Padding (e.g.: 10px 20px)")
        self.css_margin = QLineEdit(); self.css_margin.setPlaceholderText("Margin (e.g.: 0 auto)")
        self.css_display = QComboBox(); self.css_display.addItems(["(Default)", "block", "inline-block", "flex", "grid", "none"])

        css_grid.addWidget(QLabel("Width (W):"), 0, 0); css_grid.addWidget(self.css_width, 0, 1)
        css_grid.addWidget(QLabel("Cao (H):"), 0, 2); css_grid.addWidget(self.css_height, 0, 3)
        css_grid.addWidget(QLabel("Padding:"), 1, 0); css_grid.addWidget(self.css_padding, 1, 1)
        css_grid.addWidget(QLabel("Margin:"), 1, 2); css_grid.addWidget(self.css_margin, 1, 3)
        css_grid.addWidget(QLabel("Layout:"), 2, 0); css_grid.addWidget(self.css_display, 2, 1, 1, 3)
        style_layout.addWidget(css_group)
        color_layout = QHBoxLayout(); color_layout.addWidget(self.btn_bg_color); color_layout.addWidget(self.btn_text_color)
        style_layout.addLayout(color_layout)
        style_layout.addWidget(QLabel("<b>Raw CSS Code (Line by line detail):</b>"))
        style_layout.addWidget(self.inp_style, stretch=1)
        
        self.btn_apply_css = QPushButton("✔️ APPLY CSS CODE TO INTERFACE")
        self.btn_apply_css.setStyleSheet("background-color: #28a745; font-weight: bold; margin-top: 5px; padding: 10px;")
        self.btn_apply_css.clicked.connect(self.apply_changes)
        style_layout.addWidget(self.btn_apply_css)
        
        for w in [self.css_width, self.css_height, self.css_padding, self.css_margin]: w.textChanged.connect(self.on_visual_input_changed)
        self.css_display.currentTextChanged.connect(self.on_visual_input_changed)
        self.inp_style.textChanged.connect(self.on_raw_css_changed)
        self.tabs.addTab(make_scrollable(tab_style), "🎨 Visual CSS")

        tab_content = QWidget(); form_content = QVBoxLayout(tab_content); form_content.setContentsMargins(0, 0, 0, 0)
        form_content.addWidget(self.inp_text, stretch=1)
        self.tabs.addTab(tab_content, "📝 Content")

        tab_library = QWidget(); lib_layout = QVBoxLayout(tab_library); lib_layout.setContentsMargins(15, 15, 15, 15)
        
        lib_top = QHBoxLayout()
        self.btn_refresh_lib = QPushButton("🔄 Refresh list")
        self.btn_refresh_lib.clicked.connect(self.refresh_library)
        lib_top.addWidget(QLabel("<b>Source: /components/</b>"), stretch=1)
        lib_top.addWidget(self.btn_refresh_lib)
        
        self.list_library = QListWidget()
        self.list_library.setStyleSheet("QListWidget { background: #1e1e1e; border: 1px solid #3e3e42; color: #4fc1ff; font-size: 14px; } QListWidget::item { padding: 10px; border-bottom: 1px solid #333; } QListWidget::item:selected { background: #094771; color: white; font-weight: bold; }")
        
        self.btn_insert_lib = QPushButton("➕ INSERT SELECTED BLOCK INTO INTERFACE")
        self.btn_insert_lib.setStyleSheet("background-color: #0e639c; font-weight: bold; padding: 12px; margin-top: 5px;")
        self.btn_insert_lib.clicked.connect(self.insert_from_library)
        
        lib_layout.addLayout(lib_top)
        lib_layout.addWidget(self.list_library, stretch=1)
        lib_layout.addWidget(self.btn_insert_lib)
        
        self.tabs.addTab(tab_library, "📦 Library")

        action_layout = QHBoxLayout()
        btn_apply = QPushButton("⚡ Save View")
        btn_apply.setStyleSheet("background-color: #d7ba7d; color: #1e1e1e; font-weight: bold;")
        btn_apply.clicked.connect(self.apply_changes)
        
        self.btn_save = QPushButton("💾 SAVE FILE")
        self.btn_save.setStyleSheet("background-color: #28a745; font-weight: bold;")
        self.btn_save.clicked.connect(self.save_file)
        
        self.btn_zip = QPushButton("📦 Standard ZIP")
        self.btn_zip.setStyleSheet("background-color: #6c757d; font-weight: bold;")
        self.btn_zip.clicked.connect(self.export_project_to_zip)
        
        action_layout.addWidget(btn_apply, stretch=1); action_layout.addWidget(self.btn_save, stretch=1); action_layout.addWidget(self.btn_zip, stretch=1)
        
        self.btn_export_prod = QPushButton("🚀 EXPORT PRODUCTION (Split CSS & Optimize)")
        self.btn_export_prod.setStyleSheet("background-color: #e83e8c; color: white; font-weight: bold; font-size: 14px; padding: 10px; margin-top: 5px; border-radius: 4px;")
        self.btn_export_prod.clicked.connect(self.export_production_zip)
        
        bottom_layout.addLayout(action_layout)
        bottom_layout.addWidget(self.btn_export_prod)
        
        left_splitter.addWidget(bottom_container)
        left_splitter.setSizes([200, 750])

        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel); right_layout.setContentsMargins(0, 0, 0, 0)
        
        device_toolbar = QHBoxLayout(); device_toolbar.setContentsMargins(10, 5, 10, 5)
        self.lbl_current_file = QLabel("No file open...")
        self.lbl_current_file.setStyleSheet("padding: 5px; background: #333; font-weight: bold; border-radius: 4px;")
        
        self.lbl_current_file.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_current_file.setMinimumWidth(200)
        self.lbl_current_file.setMaximumWidth(350)
        
        self.btn_deselect = QPushButton("🚫 Deselect (Esc)")
        self.btn_deselect.setToolTip("Exit the currently selected object, cancel typing mode")
        self.btn_deselect.clicked.connect(self.clear_selection)
        
        self.btn_refresh_view = QPushButton("🔄 Reload View")
        self.btn_refresh_view.setToolTip("Re-render the Web view")
        self.btn_refresh_view.clicked.connect(self.update_preview)
        
        self.btn_open_browser = QPushButton("🌍 View in Browser")
        self.btn_open_browser.setToolTip("Open the current HTML file in Chrome/Edge/Safari...")
        self.btn_open_browser.clicked.connect(self.open_in_external_browser)
        
        for btn in [self.btn_deselect, self.btn_refresh_view, self.btn_open_browser]:
            btn.setStyleSheet("background: #4d4d4d; padding: 5px 12px; border-radius: 4px; font-weight: bold; color: white;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_browser.setStyleSheet("background: #28a745; padding: 5px 12px; border-radius: 4px; font-weight: bold; color: white;")
        
        sc_esc = QShortcut(QKeySequence("Esc"), self)
        sc_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_esc.activated.connect(self.clear_selection)
        
        self.cb_zoom = QComboBox()
        self.cb_zoom.addItems(["75%", "100%", "110%", "120%"])
        self.cb_zoom.setCurrentText("100%")
        self.cb_zoom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_zoom.setStyleSheet("""
            QComboBox { background: #333; padding: 4px 10px; border-radius: 4px; font-weight: bold; color: white; border: 1px solid #555; }
            QComboBox::drop-down { border-left: 1px solid #555; }
        """)
        self.cb_zoom.currentTextChanged.connect(self.change_zoom)

        self.btn_undo = QPushButton("⏪ Back")
        self.btn_undo.setToolTip("Undo previous action (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo_action)
        
        self.btn_redo = QPushButton("⏩ Forward")
        self.btn_redo.setToolTip("Redo next action (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.redo_action)
        
        for btn in [self.btn_undo, self.btn_redo]:
            btn.setStyleSheet("background: #0e639c; padding: 5px 12px; border-radius: 4px; font-weight: bold; color: white;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        sc_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        sc_redo.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_redo.activated.connect(self.redo_action)

        self.is_edit_mode = True # Default state
        self.btn_toggle_mode = QPushButton("🛠️ EDIT MODE (Click to view live)")
        self.btn_toggle_mode.setStyleSheet("background-color: #d7ba7d; color: #1e1e1e; font-weight: bold; padding: 5px 15px; border-radius: 4px; font-size: 14px;")
        self.btn_toggle_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_mode.clicked.connect(self.toggle_view_mode)

        device_toolbar.addWidget(self.lbl_current_file)
        device_toolbar.addWidget(self.btn_deselect)
        device_toolbar.addWidget(self.btn_refresh_view)
        device_toolbar.addWidget(self.btn_open_browser)
        
        device_toolbar.addStretch(1) 
        
        # ATTACH THE MODE TOGGLE BUTTON TO THE CENTER
        device_toolbar.addWidget(self.btn_toggle_mode)
        device_toolbar.addSpacing(20)

        device_toolbar.addWidget(self.btn_undo)
        device_toolbar.addWidget(self.btn_redo)
        
        device_toolbar.addWidget(QLabel("🔍 Web Zoom:"))
        device_toolbar.addWidget(self.cb_zoom)
        right_layout.addLayout(device_toolbar)

        from PySide6.QtWidgets import QStackedWidget, QStackedLayout
        from PySide6.QtWebEngineCore import QWebEngineSettings
        
        self.view_stack = QStackedWidget()
        right_layout.addWidget(self.view_stack, stretch=1)

        self.web_container = QWidget()
        self.web_container.setStyleSheet("background-color: #111111;") 
        web_layout = QHBoxLayout(self.web_container)
        web_layout.setContentsMargins(0,0,0,0)
        
        self.spacer_left = QWidget(); self.spacer_left.hide()
        self.spacer_right = QWidget(); self.spacer_right.hide()
        
        self.web_view = PreviewWebEngineView(self)
        web_layout.addWidget(self.spacer_left, stretch=1)
        web_layout.addWidget(self.web_view, stretch=0)
        web_layout.addWidget(self.spacer_right, stretch=1)
        self.view_stack.addWidget(self.web_container) # Insert into Layer 0

        self.gallery_widget = QWidget()
        self.gallery_widget.setStyleSheet("background-color: #1e1e1e;")
        gallery_layout = QVBoxLayout(self.gallery_widget)
        
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(15)
        
        self.mini_views = []
        self.mini_overlays = []
    
        for i in range(4):
            thumb_container = QWidget()
            mini_view = QWebEngineView()
            mini_view.setZoomFactor(0.3)
            mini_view.settings().setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
            mini_view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            
            overlay_btn = QPushButton()
            overlay_btn.setStyleSheet("""
                QPushButton { background-color: transparent; color: transparent; border: 2px solid #3e3e42; border-radius: 8px; }
                QPushButton:hover { background-color: rgba(0, 122, 204, 0.6); color: white; font-size: 22px; font-weight: bold; border: 2px solid #007acc; }
            """)
            
            cell_stack = QStackedLayout(thumb_container)
            cell_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
            cell_stack.addWidget(mini_view)
            cell_stack.addWidget(overlay_btn)
            
            row, col = i // 2, i % 2 
            self.grid_layout.addWidget(thumb_container, row, col)
            
            self.mini_views.append(mini_view)
            self.mini_overlays.append(overlay_btn)

        gallery_layout.addLayout(self.grid_layout, stretch=1)
        
        nav_layout = QHBoxLayout()
        self.btn_prev_tpl = QPushButton("⬅️ Previous"); self.btn_prev_tpl.clicked.connect(self.prev_template_page)
        self.lbl_page_tpl = QLabel("Trang 1 / 1"); self.lbl_page_tpl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_next_tpl = QPushButton("Sau ➡️"); self.btn_next_tpl.clicked.connect(self.next_template_page)
        
        btn_style = "background: #007acc; color: white; padding: 10px; font-weight: bold; border-radius: 4px;"
        self.btn_prev_tpl.setStyleSheet(btn_style)
        self.btn_next_tpl.setStyleSheet(btn_style)
        self.lbl_page_tpl.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        
        nav_layout.addWidget(self.btn_prev_tpl)
        nav_layout.addWidget(self.lbl_page_tpl, stretch=1)
        nav_layout.addWidget(self.btn_next_tpl)
        gallery_layout.addLayout(nav_layout)
        
        self.view_stack.addWidget(self.gallery_widget) # Insert into Layer 1
        
        self.view_stack.setCurrentIndex(0)
        self.template_files = []
        self.current_tpl_page = 0

        main_splitter.addWidget(left_panel); main_splitter.addWidget(right_panel)

        main_splitter.setSizes([360, 1240])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        
        self.clear_form()
        self.refresh_library()
        
        self.change_zoom(self.cb_zoom.currentText())

    def toggle_view_mode(self):
        self.is_edit_mode = not getattr(self, 'is_edit_mode', True)
        if self.is_edit_mode:
            self.btn_toggle_mode.setText("🛠️ EDIT MODE (Click to view live)")
            self.btn_toggle_mode.setStyleSheet("background-color: #d7ba7d; color: #1e1e1e; font-weight: bold; padding: 5px 15px; border-radius: 4px; font-size: 14px;")
            self.web_view.page().runJavaScript("window.isEditMode = true;")
            self.statusBar().showMessage("🛠️ IN EDIT MODE: Right-click, Select tag, Safely edit text enabled.", 4000)
        else:
            self.btn_toggle_mode.setText("👁️ VIEW MODE (Click to edit)")
            self.btn_toggle_mode.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 5px 15px; border-radius: 4px; font-size: 14px;")
            self.clear_selection()
            self.web_view.page().runJavaScript("window.isEditMode = false; document.querySelectorAll('.editor-highlight').forEach(e => e.classList.remove('editor-highlight'));")
            self.statusBar().showMessage("👁️ IN VIEW MODE: You can click Tabs, Accordions, Links... just like a real website!", 4000)

    def clear_selection(self):
        self.current_node = None
        self.last_active_eid = ""
        self.tree.clearSelection()
        self.clear_form()
        self.lbl_breadcrumb.setText("📌 No tag selected")
        
        js_clear = """
        (function() {
            // 1. Remove all highlight borders
            document.querySelectorAll('.editor-highlight, .editor-hover').forEach(e => {
                e.classList.remove('editor-highlight', 'editor-hover');
            });
            // 2. Exit typing mode (contenteditable)
            if (window.currentEditingEl) {
                window.currentEditingEl.removeAttribute('contenteditable');
                window.currentEditingEl = null;
            }
            // 3. Clear selected/highlighted text
            window.getSelection().removeAllRanges();
            // 4. Remove mouse focus from the current element
            if (document.activeElement) {
                document.activeElement.blur();
            }
        })();
        """
        self.web_view.page().runJavaScript(js_clear)
        self.statusBar().showMessage("🚫 Selection cleared and interface released!", 3000)

    def open_in_external_browser(self):
        if not self.current_file_path or not os.path.exists(self.current_file_path):
            QMessageBox.warning(self, "No file", "You need to Open a file or Save a file before you can view it in an external browser!")
            return
        
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_file_path))
        self.statusBar().showMessage("🌍 File opened in the default browser!", 3000)

    def get_relative_path(self, title, filter_str):
        if not self.current_file_path: return ""
        b_dir = os.path.dirname(self.current_file_path)
        f_path, _ = QFileDialog.getOpenFileName(self, title, b_dir, filter_str)
        
        if not f_path: return ""
        
        try:
            return os.path.relpath(f_path, b_dir).replace('\\', '/')
        except ValueError:

            return f_path

    def browse_href_file(self):
        # Extend the filter to allow selecting both HTML and Markdown (.md)
        p = self.get_relative_path("Select File", "Documents (*.html *.htm *.md);;All Files (*.*)")
        if p: self.inp_href.setText(p)

    def browse_src_file(self):
        p = self.get_relative_path("Select Image", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if p: self.inp_src.setText(p)

    def save_state_for_undo(self):
        if not hasattr(self, 'undo_stack'): self.undo_stack = []
        if not hasattr(self, 'redo_stack'): self.redo_stack = []
        if self.soup:
            self.undo_stack.append(str(self.soup))
            if len(self.undo_stack) > 50: self.undo_stack.pop(0)
            self.redo_stack.clear()

    def undo_action(self):
        if not hasattr(self, 'undo_stack') or not self.undo_stack:
            self.statusBar().showMessage("Already at the oldest state, cannot go Back further!", 3000)
            return
        if not hasattr(self, 'redo_stack'): self.redo_stack = []
        
        self.redo_stack.append(str(self.soup))
        self.soup = self.parse_html(self.undo_stack.pop())
        self.refresh_tree(); self.update_preview()
        self.statusBar().showMessage("⏪ Back (Undo) successful!", 3000)

    def redo_action(self):
        if not hasattr(self, 'redo_stack') or not self.redo_stack:
            self.statusBar().showMessage("Already at the newest state, cannot go Forward further!", 3000)
            return
        if not hasattr(self, 'undo_stack'): self.undo_stack = []
        
        self.undo_stack.append(str(self.soup))
        self.soup = self.parse_html(self.redo_stack.pop())
        self.refresh_tree(); self.update_preview()
        self.statusBar().showMessage("⏩ Forward (Redo) successful!", 3000)

    def parse_html(self, content):
        try: return BeautifulSoup(content, 'lxml')
        except: return BeautifulSoup(content, 'html.parser')

    def load_file_dialog(self):

        if hasattr(self, 'view_stack'):
            self.view_stack.setCurrentIndex(0)

        p, _ = QFileDialog.getOpenFileName(self, "Select HTML File", BASE_DIR, "HTML (*.html *.htm)")
        if p:
            if not os.path.exists(p):
                QMessageBox.warning(self, "Ghost File Warning", f"This file does not exist on disk!\nIt may have already been deleted, or it is a stray entry incorrectly shown by Windows Explorer.\nPath: {p}")
                return
                
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                    self.soup = self.parse_html(f.read())
                    
                # --- AUTO CLEANUP: Scrub duplicated stray script tags left over from the old Tool version ---
                for s in self.soup.find_all('script'):
                    if not s.has_attr('src') and not s.has_attr('id') and s.string and "EDITOR_SCROLL" in s.string:
                        s.decompose()
                        
                # FIX: Always lock the file using the Absolute Path
                self.current_file_path = os.path.abspath(p)
                
                # Reinitialize the Undo/Redo stack when opening a new file
                if hasattr(self, 'undo_stack'): self.undo_stack.clear()
                if hasattr(self, 'redo_stack'): self.redo_stack.clear()
                
                self.lbl_current_file.setText(f"Viewing: <b>{os.path.basename(p)}</b>")
                self.refresh_tree(); self.update_preview()
            except Exception as e:
                QMessageBox.critical(self, "Error Opening File", f"Could not read this file:\n{str(e)}")

    def format_node_title(self, child):
        icons = {'div':'📦', 'section':'🧱', 'a':'🔗', 'img':'🖼️', 'button':'🔘', 'p':'💬'}
        ic = icons.get(child.name, '🏷️')
        id_s = f" #{child.get('id')}" if child.get('id') else ""
        cl = child.get('class', [])
        cl_s = f" .{cl[0]}" if cl else ""
        txt = child.get_text(strip=True)[:30]
        tx_s = f' ➔ "{txt}..."' if txt and len(child.find_all())<2 else ""

        return f"{ic} {child.name}{id_s}{cl_s}{tx_s}"

    def refresh_tree(self):
        self.tree.clear(); self.current_node = None; self.node_map = {}; self.clear_form()
        if not self.soup: return
        r_node = self.soup.find('body') or self.soup.find('html') or self.soup
        r_item = QTreeWidgetItem(self.tree, ["🌐 Root"])
        r_item.setData(0, Qt.ItemDataRole.UserRole, r_node)
        r_id = str(id(r_node))
        r_node['data-editor-id'] = r_id
        r_item.setData(0, Qt.ItemDataRole.UserRole + 1, r_id)
        self.node_map[r_id] = r_item
        self.build_dom_tree(r_item, r_node, 1)
        r_item.setExpanded(True)

    def build_dom_tree(self, p_item, p_node, depth):
        for c in p_node.children:
            if isinstance(c, Tag) and c.name not in ['script', 'style', 'meta', 'link', 'head']:
                item = QTreeWidgetItem(p_item, [self.format_node_title(c)])
                item.setData(0, Qt.ItemDataRole.UserRole, c)
                e_id = str(id(c))
                c['data-editor-id'] = e_id
                item.setData(0, Qt.ItemDataRole.UserRole + 1, e_id)
                self.node_map[e_id] = item
                self.build_dom_tree(item, c, depth + 1)
                if depth <= 2: p_item.setExpanded(True)

    def clear_form(self):
        for w in [self.inp_tag, self.inp_id, self.inp_class, self.inp_style, self.inp_data_trang, self.inp_href, self.inp_src]: 
            w.clear()
            
        self.inp_text.page().runJavaScript("if(window.editor) { window.editor.setValue('<!-- Select a tag to view the HTML code -->'); }")
        
        for w in [self.inp_href, self.inp_src, self.btn_browse_href, self.btn_browse_src]: 
            w.setEnabled(False)
            
        if hasattr(self, 'lbl_src'):
            self.lbl_src.setVisible(False)
            self.w_src.setVisible(False)
            self.chk_img_responsive.setVisible(False)

    def on_item_clicked(self, item, col):
        tag = item.data(0, Qt.ItemDataRole.UserRole)
        eid = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not tag or not isinstance(tag, Tag): return
        
        self.current_node = tag
        self.last_active_eid = eid 
        
        self.inp_tag.setText(tag.name)
        self.inp_id.setText(tag.get('id', ''))
        cl = tag.get('class')
        self.inp_class.setText(" ".join(cl) if isinstance(cl, list) else (cl or ""))
        
        style_str = tag.get('style', '')
        if isinstance(style_str, list): style_str = " ".join(style_str)
        formatted_css = ""
        if style_str:
            for p in style_str.split(';'):
                if ':' in p:
                    k, v = p.split(':', 1)
                    formatted_css += f"{k.strip().lower()}: {v.strip()};\n" 

        self.inp_style.setPlainText(formatted_css.strip())
        self.inp_data_trang.setText(tag.get('data-trang', '')) 
        self.inp_href.setText(tag.get('href', ''))
        self.inp_src.setText(tag.get('src', ''))
        
        raw_html = tag.decode_contents()
        b64_html = base64.b64encode(raw_html.encode('utf-8')).decode('utf-8')
        inject_js = f"if(window.editor) {{ window.editor.setValue(decodeURIComponent(escape(window.atob('{b64_html}')))); }}"
        self.inp_text.page().runJavaScript(inject_js)

        is_l = tag.name in ['a', 'link']
        is_m = tag.name in ['img', 'script', 'iframe', 'video']
        is_f = tag.name == 'form' # <--- Added Form detection

        self.inp_href.setEnabled(is_l)
        self.btn_browse_href.setEnabled(is_l)
        self.btn_make_link.setVisible(not is_l) 
        
        self.lbl_src.setVisible(is_m)
        self.w_src.setVisible(is_m)
        self.inp_src.setEnabled(is_m)
        self.btn_browse_src.setEnabled(is_m)

        self.lbl_form.setVisible(is_f)
        self.w_form.setVisible(is_f)
        if is_f:
            self.inp_form_action.setText(tag.get('action', ''))
            self.inp_form_method.blockSignals(True)
            self.inp_form_method.setCurrentText(str(tag.get('method', 'POST')).upper())
            self.inp_form_method.blockSignals(False)

        self.chk_img_responsive.setVisible(tag.name == 'img')
        if tag.name == 'img':
            st_str = str(tag.get('style', '')).lower()
            self.chk_img_responsive.setChecked('max-width' in st_str or '100%' in st_str)
        else:
            self.chk_img_responsive.setChecked(False)

        path = []
        curr_item = item
        while curr_item:
            text_node = curr_item.text(0)
            clean_name = text_node.split(' ', 1)[1] if ' ' in text_node else text_node
            if ' ➔ ' in clean_name: clean_name = clean_name.split(' ➔ ')[0]
            path.insert(0, clean_name)
            curr_item = curr_item.parent()
        self.lbl_breadcrumb.setText("📌 " + " ➔ ".join(path))

        data_trang = tag.get('data-trang')
        if data_trang:

            main_container = self.soup.find('main') or self.soup.find(class_='vung-noi-dung-chinh') or self.soup.find('body')
            if main_container:
                for page in main_container.find_all(class_='trang-noi-dung'):
                    cls = page.get('class', [])
                    if isinstance(cls, str): cls = [cls]
                    if 'trang-dang-hien-thi' in cls: cls.remove('trang-dang-hien-thi')
                    page['class'] = cls
                    st = str(page.get('style', ''))
                    if 'display: block' in st: page['style'] = st.replace('display: block', 'display: none')
                    elif 'display' not in st: page['style'] = st.strip(';') + ("; " if st else "") + "display: none;"
                    
                target_page = self.soup.find(id=data_trang)
                if target_page:
                    cls = target_page.get('class', [])
                    if isinstance(cls, str): cls = [cls]
                    if 'trang-dang-hien-thi' not in cls: cls.append('trang-dang-hien-thi')
                    target_page['class'] = cls
                    st = str(target_page.get('style', ''))
                    if 'display: none' in st: target_page['style'] = st.replace('display: none', 'display: block')
                    elif 'display' not in st: target_page['style'] = st.strip(';') + ("; " if st else "") + "display: block;"

                for btn in self.soup.find_all(class_='nut-chuyen-trang'):
                    cls = btn.get('class', [])
                    if isinstance(cls, str): cls = [cls]
                    if 'menu-dang-chon' in cls: cls.remove('menu-dang-chon')
                    btn['class'] = cls
                    
                cls = tag.get('class', [])
                if isinstance(cls, str): cls = [cls]
                if 'menu-dang-chon' not in cls: cls.append('menu-dang-chon')
                tag['class'] = cls

            js_switch = f"""
            (function() {{
                document.querySelectorAll('.trang-noi-dung').forEach(function(el){{ el.classList.remove('trang-dang-hien-thi'); el.style.display='none'; }});
                var target = document.getElementById('{data_trang}'); 
                if(target) {{ target.classList.add('trang-dang-hien-thi'); target.style.display='block'; }}
                document.querySelectorAll('.nut-chuyen-trang').forEach(function(btn){{ btn.classList.remove('menu-dang-chon'); }});
                var activeBtn = document.querySelector('[data-trang="{data_trang}"]');
                if(activeBtn) activeBtn.classList.add('menu-dang-chon');
            }})();
            """
            self.web_view.page().runJavaScript(js_switch)
            self.statusBar().showMessage(f"👁️ Opened workspace: {data_trang}", 3000)

        if eid:
            # --- ULTIMATE FIX TO SAVE COPY/PASTE: Preserve the currently highlighted text region ---
            js = f"""
            (function() {{
                var sel = window.getSelection();
                var ranges = [];
                // 1. Store the highlighted region in a safe
                if (sel && sel.rangeCount > 0) {{
                    for(var i=0; i<sel.rangeCount; i++) ranges.push(sel.getRangeAt(i));
                }}
                
                // 2. Change the CSS class that draws the blue border
                document.querySelectorAll('.editor-highlight').forEach(e => e.classList.remove('editor-highlight')); 
                var el = document.querySelector('[data-editor-id="{eid}"]'); 
                if(el) {{ el.classList.add('editor-highlight'); }}
                
                // 3. Restore the highlighted region for the user
                if (sel && ranges.length > 0) {{
                    sel.removeAllRanges();
                    ranges.forEach(r => sel.addRange(r));
                }}
            }})();
            """
            self.web_view.page().runJavaScript(js, 0)

    def select_tree_item_by_id(self, eid):
        if eid in self.node_map:
            item = self.node_map[eid]
            p = item.parent()
            while p: p.setExpanded(True); p = p.parent()
            self.tree.setCurrentItem(item); self.tree.scrollToItem(item); self.on_item_clicked(item, 0)

    def on_visual_input_changed(self):
        self.inp_style.blockSignals(True)
        
        w = self.css_width.text().strip()
        h = self.css_height.text().strip()
        p = self.css_padding.text().strip()
        m = self.css_margin.text().strip()
        d = self.css_display.currentText()

        st = self.inp_style.toPlainText().strip()
        style_dict = {}
        if st:
            for rule in st.split(';'):
                if ':' in rule:
                    k, v = rule.split(':', 1)
                    style_dict[k.strip().lower()] = v.strip()

        def set_or_del(k, val):
            if val and val != "(Default)": style_dict[k] = val
            elif k in style_dict: del style_dict[k]

        set_or_del('width', w)
        set_or_del('height', h)
        set_or_del('padding', p)
        set_or_del('margin', m)
        set_or_del('display', d)

        new_style = ""
        for k, val in style_dict.items():
            new_style += f"{k}: {val};\n"

        self.inp_style.setPlainText(new_style.strip())
        self.inp_style.blockSignals(False)

    def on_raw_css_changed(self):
        st = self.inp_style.toPlainText().strip()
        style_dict = {}
        if st:
            for rule in st.split(';'):
                if ':' in rule:
                    k, v = rule.split(':', 1)
                    style_dict[k.strip().lower()] = v.strip()

        def set_silent(widget, value, is_combo=False):
            widget.blockSignals(True)
            if is_combo:
                idx = widget.findText(value)
                widget.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                widget.setText(value)
            widget.blockSignals(False)

        # Automatically extract keys like width, height... to populate the Form.
        set_silent(self.css_width, style_dict.get('width', ''))
        set_silent(self.css_height, style_dict.get('height', ''))
        set_silent(self.css_padding, style_dict.get('padding', ''))
        set_silent(self.css_margin, style_dict.get('margin', ''))
        set_silent(self.css_display, style_dict.get('display', '(Default)'), True)

    def pick_bg_color(self):
        c = QColorDialog.getColor(QColor(), self, "Select Background Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid(): 
            rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()/255.0:g})"
            self.update_style_property('background-color', rgba)

    def pick_text_color(self):
        c = QColorDialog.getColor(QColor(), self, "Select Text Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid(): 
            rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()/255.0:g})"
            self.update_style_property('color', rgba)

    def update_style_property(self, prop, val):
        current_css = self.inp_style.toPlainText().strip()
        if current_css and not current_css.endswith(';'): current_css += ';'
        self.inp_style.setPlainText(current_css + f"\n{prop}: {val};")
        self.apply_changes()

    def sync_resize_from_web(self, eid, w, h):
        if self.current_node and self.current_node.get('data-editor-id') == eid:
            self.save_state_for_undo()
            
            st = self.inp_style.toPlainText().strip()
            style_dict = {}
            if st:
                for rule in st.split(';'):
                    if ':' in rule:
                        k, v = rule.split(':', 1)
                        style_dict[k.strip().lower()] = v.strip()

            is_img = self.current_node.name in ['img', 'video', 'iframe']

           
            if h and h != '0px' and not is_img:
                style_dict['min-height'] = h
                if 'height' in style_dict: del style_dict['height']

            
            if w and w != '0px':
                is_flex_child = False
                
                if self.current_node.parent:
                    p_style = str(self.current_node.parent.get('style', '')).replace(' ', '').lower()
                    p_class = str(self.current_node.parent.get('class', '')).lower()
                    if 'flex' in p_style or 'grid' in p_style or 'row' in p_class or 'wrap' in p_class:
                        is_flex_child = True

                if is_img:
                   
                    style_dict['width'] = w
                    if h and h != '0px':
                        style_dict['height'] = h
                    else:
                        style_dict['height'] = 'auto'
                    
                    style_dict['max-width'] = '100%' # Keep Responsive so it doesn't overflow on mobile screens
                    if 'flex' in style_dict: del style_dict['flex']

                elif is_flex_child:
                    style_dict['flex'] = f'0 0 {w}'
                    style_dict['max-width'] = '100%'
                    if 'width' in style_dict: del style_dict['width']
                else:
                    style_dict['width'] = w
                    style_dict['max-width'] = '100%'
                    if 'flex' in style_dict: del style_dict['flex']

            new_style = "; ".join([f"{k}: {v}" for k, v in style_dict.items()])
            if new_style:
                self.current_node['style'] = new_style
            else:
                if 'style' in self.current_node.attrs: del self.current_node['style']

            self.css_width.blockSignals(True)
            self.css_height.blockSignals(True)
            
            if 'flex' in style_dict: self.css_width.setText(style_dict['flex'].replace('0 0 ', ''))
            elif 'width' in style_dict: self.css_width.setText(style_dict['width'])
            
            if 'height' in style_dict and is_img: self.css_height.setText(style_dict['height'])
            elif 'min-height' in style_dict: self.css_height.setText(style_dict['min-height'])
            
            self.inp_style.setPlainText(new_style.replace("; ", ";\n"))
            self.css_width.blockSignals(False)
            self.css_height.blockSignals(False)
            
            self.statusBar().showMessage("🔒 New size applied! Adjacent tags have automatically resized accordingly.", 5000)

    def sync_drag_pos_from_web(self, eid, left, top):
        target = self.soup.find(attrs={"data-editor-id": eid})
        if target:
            self.save_state_for_undo() 
            st = str(target.get('style', ''))
            import re
            
            st = re.sub(r'left:\s*[^;]+;?', '', st)
            st = re.sub(r'top:\s*[^;]+;?', '', st)
            st = st.strip(';') + ("; " if st else "") + f"left: {left}; top: {top};"
            target['style'] = st.strip('; ')

            if self.current_node and self.current_node.get('data-editor-id') == eid:
                self.inp_style.blockSignals(True)
                formatted = "\n".join([f"{k.strip()}: {v.strip()};" for k, v in [rule.split(':', 1) for rule in st.split(';') if ':' in rule]])
                self.inp_style.setPlainText(formatted)
                self.inp_style.blockSignals(False)
                
            self.statusBar().showMessage("🛸 New position coordinates saved!", 3000)


    def exec_text_cmd(self, cmd, val=None):
        self.save_state_for_undo()
        val_str = f", '{val}'" if val else ", null"
        
        js = f"""
        (function() {{
            // 1. Retrieve the highlighted region saved on right-click
            if (window.lastSelectionRange) {{
                var sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(window.lastSelectionRange);
            }}
            
            // 2. Force the text container into edit state so execCommand works
            var node = window.getSelection().anchorNode;
            if (node) {{
                var el = node.nodeType === 3 ? node.parentNode : node;
                var ce = el.closest('[data-editor-id]');
                if (ce) ce.setAttribute('contenteditable', 'true');
            }}
            
            // 3. Execute the command
            document.execCommand('{cmd}', false{val_str});
        }})();
        """
        self.web_view.page().runJavaScript(js, 0, lambda r: self.sync_from_preview())
        self.statusBar().showMessage(f"📝 Text formatted ({cmd})!", 3000)

    def change_font_size(self, t, delta):
        self.save_state_for_undo()
        st = str(t.get('style', ''))
        import re
        match = re.search(r'font-size:\s*(\d+)px', st)
        current_size = int(match.group(1)) if match else 16
        new_size = max(8, current_size + delta)
        
        if 'font-size' in st:
            new_st = re.sub(r'font-size:\s*\d+px', f'font-size: {new_size}px', st)
        else:
            new_st = st.strip(';') + ("; " if st else "") + f"font-size: {new_size}px;"
            
        t['style'] = new_st.strip('; ')
        
        item = self.tree.currentItem()
        if item: self.on_item_clicked(item, 0)
        self.apply_changes()
        self.statusBar().showMessage(f"📏 Font size of entire tag changed to {new_size}px", 3000)

    def change_text_align(self, t, align):
        self.save_state_for_undo()
        st = str(t.get('style', ''))
        import re
        if 'text-align' in st:
            new_st = re.sub(r'text-align:\s*\w+;?', f'text-align: {align};', st)
        else:
            new_st = st.strip(';') + ("; " if st else "") + f"text-align: {align};"
        t['style'] = new_st.strip('; ')
        
        item = self.tree.currentItem()
        if item: self.on_item_clicked(item, 0)
        self.apply_changes()
        self.statusBar().showMessage(f"Text alignment: {align}", 3000)

    def insert_quick_html(self, t, html_str):
        self.save_state_for_undo()
        new_soup = self.parse_html(html_str)
        nodes = list((new_soup.body or new_soup).children)
        for n in nodes:
            if n.name: t.append(n)
                
        self.refresh_tree()
        self.update_preview()
        self.statusBar().showMessage("➕ New text box added!", 3000)

    def insert_floating_textbox(self, t):
        html = '''<div style="position: relative; padding: 15px; margin: 10px 0; background: rgba(255,255,255,0.05); border: none; color: inherit; resize: both; overflow: auto; min-height: 100px; min-width: 150px; border-radius: 8px;">
            <h3 style="margin-top:0; color:#007acc;">Box Title</h3>
            <p>Enter free-form text content. Note the handle in the bottom-right corner lets you resize the box!</p>
        </div>'''
        self.insert_quick_html(t, html)

    def toggle_border(self, item, t):
        self.save_state_for_undo()
        st = str(t.get('style', ''))
        import re
        
        if st and not st.endswith(';'): st += ';'
        
        if 'border:' in st and 'none' not in st:
            st = re.sub(r'border:[^;]+;', 'border: none;', st)
            msg = "🚫 Box border disabled!"
        elif 'border: none' in st:
            st = st.replace('border: none;', 'border: 2px dashed #007acc;')
            msg = "🔲 Box border enabled!"
        else:
            st += " border: 2px dashed #007acc;"
            msg = "🔲 Box border enabled!"
            
        t['style'] = st.strip('; ')
        
        self.on_item_clicked(item, 0)
        self.apply_changes()
        self.statusBar().showMessage(msg, 3000)

    def change_selected_text_color(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor()
        if c.isValid():
            self.exec_text_cmd('foreColor', c.name())

    def apply_changes(self):
        if not self.current_node: return
        self.inp_text.page().runJavaScript("window.editor ? window.editor.getValue() : ''", 0, self._process_apply_changes)

    def _process_apply_changes(self, editor_html):
        self.save_state_for_undo()
        t = self.current_node

        nt = self.inp_tag.text().strip().lower()
        if nt: t.name = nt
        
        def upd(k, v, is_list=False):
            if v: t[k] = v.split() if is_list else v
            elif k in t.attrs: del t[k]
            
        upd('id', self.inp_id.text().strip())
        upd('class', self.inp_class.text().strip(), True)
        
        css_oneline = self.inp_style.toPlainText().replace('\n', ' ').strip()
        upd('style', css_oneline)
        upd('data-trang', self.inp_data_trang.text().strip())

        if t.name == 'form':
            upd('action', self.inp_form_action.text().strip())
            upd('method', self.inp_form_method.currentText())

        if self.inp_href.isEnabled():
            href_val = self.inp_href.text().strip()
            old_src = t.get('src', '')
            new_src = self.inp_src.text().strip()
            if new_src:
                upd('src', new_src)
                for attr in list(t.attrs.keys()):
                    if attr in ['onerror', 'data-src', 'data-lazy', 'srcset']:
                        val = str(t[attr])
                        if old_src and old_src in val:
                            t[attr] = val.replace(old_src, new_src)
                        elif "this.src=" in val:
                            t[attr] = f"this.src='{new_src}'"
                            
            if t.name == 'img' and self.chk_img_responsive.isChecked():
                st = str(t.get('style', ''))
                if "max-width" not in st:
                    t['style'] = (st + "; max-width: 100%; height: auto; object-fit: contain;").strip("; ")

        t.clear()
        if editor_html.strip():
            ns = self.parse_html(editor_html)
            for c in list((ns.body or ns).children): t.append(c)

        s_items = self.tree.selectedItems()
        if s_items:
            i = s_items[0]
            i.setText(0, self.format_node_title(t))
            i.takeChildren()
            self.build_dom_tree(i, t, 99)
            i.setExpanded(True)          

        if t.name not in ['body', 'html']:
            eid = t.get('data-editor-id')
            import base64
            b64_html = base64.b64encode(str(t).encode('utf-8')).decode('utf-8')
            js = f"""
            (function(){{
                var el = document.querySelector('[data-editor-id="{eid}"]');
                if(el) {{
                    var temp = document.createElement('div');
                    temp.innerHTML = decodeURIComponent(escape(window.atob('{b64_html}')));
                    var newEl = temp.firstElementChild;
                    if(newEl) {{
                        el.replaceWith(newEl);
                        // Re-activate the blue border hugging the tag after replacement
                        setTimeout(() => newEl.classList.add('editor-highlight'), 50);
                    }}
                }}
            }})();
            """
            self.web_view.page().runJavaScript(js)
            self.statusBar().showMessage("✅ Changes updated (No page reload at all)!", 3000)
        else:
            self.update_preview()
            self.statusBar().showMessage("✅ Entire page reloaded!", 3000)

    def update_preview(self):
        if not self.soup: return
        html = str(self.soup)
        
        if 'name="viewport"' not in html.lower():
            meta_tag = '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">'
            if '<head>' in html.lower():
                html = html.replace('<head>', f'<head>\n    {meta_tag}')
            else:
                html = html.replace('<html>', f'<html>\n<head>\n    {meta_tag}\n</head>')

        # Inject the Tool current state into JS
        edit_mode_str = 'true' if getattr(self, 'is_edit_mode', True) else 'false'

        js = f"""
        <style id="mini-app-editor-style">
            * {{ box-sizing: border-box !important; }}
            img, video, iframe {{ max-width: 100% !important; height: auto !important; object-fit: contain; }}
            p, h1, h2, h3, h4, h5, h6, span, div, a {{ max-width: 100%; word-wrap: break-word !important; overflow-wrap: break-word !important; }}
            .editor-highlight {{ outline: 3px solid #007acc !important; box-shadow: inset 0 0 15px rgba(0,122,204,0.4) !important; transition: outline 0.2s, box-shadow 0.2s; }}
            .editor-hover {{ outline: 2px dashed #ff9800 !important; cursor: crosshair !important; transition: outline 0.1s; }}
            [contenteditable="true"] {{ outline: 2px dashed #4CAF50 !important; cursor: text !important; }}
            html, body {{ overflow-x: hidden !important; }}
        </style>
        <script id="mini-app-editor-script">
            window.lastClickTarget = null;
            window.currentEditingEl = null;
            window.lastSelectionRange = null; 
            window.isEditMode = {edit_mode_str}; // <--- ULTIMATE CONTROL VARIABLE
            
            let lastWidth = "";
            let lastHeight = "";

            /* --- FLOATING IMAGE DRAG ENGINE (FREE FLOATING) --- */
            let activeDragEl = null;
            let startMouseX = 0, startMouseY = 0;
            let startElLeft = 0, startElTop = 0;

            document.addEventListener('mousedown', function(e) {{ 
                if(!window.isEditMode) return; 
                window.focus(); 
                
                var t = e.target;
                if(t.classList && t.classList.contains('free-floating-element')) {{
                    activeDragEl = t;
                    startMouseX = e.clientX;
                    startMouseY = e.clientY;
                    // Get the current position of the tag
                    startElLeft = parseFloat(window.getComputedStyle(t).left) || 0;
                    startElTop = parseFloat(window.getComputedStyle(t).top) || 0;
                    e.preventDefault(); // Block the browser's default image drag behavior
                    return;
                }}
                
                var hl = document.querySelector('.editor-highlight'); 
                if (hl) {{ lastWidth = hl.style.width; lastHeight = hl.style.height; }} 
            }}, true);
            
            document.addEventListener('mousemove', function(e) {{
                if(!window.isEditMode) return;
                
                // Drag & Drop algorithm
                if (activeDragEl) {{
                    var dx = e.clientX - startMouseX;
                    var dy = e.clientY - startMouseY;
                    activeDragEl.style.left = (startElLeft + dx) + 'px';
                    activeDragEl.style.top = (startElTop + dy) + 'px';
                }}
            }}, true);

            document.addEventListener('mouseup', function(e) {{
                if(!window.isEditMode) return;
                
                if (activeDragEl) {{
                    var eid = activeDragEl.getAttribute('data-editor-id');
                    var finalLeft = activeDragEl.style.left;
                    var finalTop = activeDragEl.style.top;
                    if(eid) console.log("EDITOR_DRAG_POS:" + eid + "|" + finalLeft + "|" + finalTop);
                    activeDragEl = null;
                    return;
                }}
                
                var hl = document.querySelector('.editor-highlight');
                if (hl) {{
                    var w = hl.style.width;
                    var h = hl.style.height;
                    if (w !== lastWidth || h !== lastHeight) {{
                        var eid = hl.getAttribute('data-editor-id');
                        if(eid) console.log("EDITOR_RESIZE:" + eid + "|" + w + "|" + h);
                        lastWidth = w;
                        lastHeight = h;
                    }}
                }}
            }}, true);

            document.addEventListener('mouseover', function(e) {{
                if(!window.isEditMode || activeDragEl) return; // Lock border while dragging
                var eid = e.target.getAttribute('data-editor-id');
                if(!eid) {{
                    var hl = e.target.closest('[data-editor-id]');
                    if(hl) eid = hl.getAttribute('data-editor-id');
                }}
                document.querySelectorAll('.editor-hover').forEach(el => el.classList.remove('editor-hover'));
                if (eid) {{
                    var target = document.querySelector('[data-editor-id="'+eid+'"]');
                    if (target && !target.classList.contains('editor-highlight')) target.classList.add('editor-hover');
                }}
            }}, true);
            
            document.addEventListener('mouseout', function(e) {{
                if(!window.isEditMode) return;
                document.querySelectorAll('.editor-hover').forEach(el => el.classList.remove('editor-hover'));
            }}, true);
            
            document.addEventListener('submit', function(e) {{
                if(!window.isEditMode) return;
                e.preventDefault();
                console.log("EDITOR_HINT:🚫 Form Submit was blocked in Edit Mode.");
            }}, true);

            document.addEventListener('click', function(e) {{ 
                if(!window.isEditMode) return;
                
                var aTag = e.target.closest('a');
                var btnTag = e.target.closest('button');
                
                if (aTag || btnTag) {{
                    e.preventDefault();
                    if (aTag) {{
                        var href = aTag.getAttribute('href');
                        if (href && (e.ctrlKey || e.metaKey)) {{
                            console.log("EDITOR_OPEN_LINK:" + href);
                        }} else if (href && href !== '#' && !href.startsWith('javascript:')) {{
                            console.log("EDITOR_HINT:💡 In EDIT mode so the Tool blocks page navigation! Switch to VIEW mode or hold Ctrl+Click to test.");
                        }}
                    }}
                }}

                var t = e.target;
                if (window.currentEditingEl && window.currentEditingEl.contains(t)) return; 
                
                if (window.currentEditingEl) {{
                    window.currentEditingEl.removeAttribute('contenteditable');
                    window.currentEditingEl = null;
                    console.log("EDITOR_HINT:✅ Text saved locally.");
                }}

                if(t.tagName==='IMG' || t.querySelector('img')) window.lastClickTarget = t;
                var eid = t.getAttribute('data-editor-id');
                var hl = t;
                if(!eid) {{ hl = t.closest('[data-editor-id]'); if(hl) eid = hl.getAttribute('data-editor-id'); }}
                if(eid) {{ 
                    console.log("EDITOR_CLICK:" + eid); 
                    document.querySelectorAll('.editor-highlight').forEach(el => el.classList.remove('editor-highlight'));
                    document.querySelectorAll('.editor-hover').forEach(el => el.classList.remove('editor-hover'));
                    if(hl) hl.classList.add('editor-highlight');
                }}
            }}, true);
            
            document.addEventListener('dblclick', function(e) {{
                if(!window.isEditMode) return;
                var t = e.target;
                var forbiddenTags = ['BODY', 'HTML', 'IMG', 'HR', 'BR', 'INPUT', 'VIDEO', 'IFRAME']; 
                
                if (!forbiddenTags.includes(t.tagName) && !t.classList.contains('free-floating-element')) {{
                    e.preventDefault();
                    e.stopPropagation(); 
                    t.setAttribute('contenteditable', 'true');
                    t.focus();
                    window.currentEditingEl = t;
                    console.log("EDITOR_EDIT_MODE:"); 
                }}
            }}, true);
            
            document.addEventListener('contextmenu', function(e) {{ 
                if(!window.isEditMode) return;
                e.preventDefault();
                window.lastContextTarget = e.target;
                
                var sel = window.getSelection();
                if(sel.rangeCount > 0 && sel.toString().trim() !== "") {{
                    window.lastSelectionRange = sel.getRangeAt(0);
                }} else {{
                    window.lastSelectionRange = null;
                }}
                
                var t = e.target;
                var eid = t.getAttribute('data-editor-id');
                var hl = t;
                if(!eid) {{ hl = t.closest('[data-editor-id]'); if(hl) eid = hl.getAttribute('data-editor-id'); }}
                if(eid) {{
                    document.querySelectorAll('.editor-highlight').forEach(el => el.classList.remove('editor-highlight'));
                    document.querySelectorAll('.editor-hover').forEach(el => el.classList.remove('editor-hover'));
                    if(hl) hl.classList.add('editor-highlight');
                    console.log("EDITOR_CONTEXT:" + eid);
                }}
            }}, true);
        </script>"""
        
        js = js.replace('\xa0', ' ')

        sx = getattr(self, 'current_scroll_x', 0)
        sy = getattr(self, 'current_scroll_y', 0)
        active_eid = getattr(self, 'last_active_eid', "")
        
        scroll_fix_js = f"""
            (function() {{
                window.scrollTo({{left: {sx}, top: {sy}, behavior: 'instant'}});
                var scrollTimeout;
                window.addEventListener('scroll', function() {{
                    clearTimeout(scrollTimeout);
                    scrollTimeout = setTimeout(function() {{
                        console.log("EDITOR_SCROLL:" + window.scrollX + "|" + window.scrollY);
                    }}, 100);
                }}, {{ passive: true }});

                document.addEventListener('DOMContentLoaded', function() {{
                    var activeEid = "{active_eid}";
                    if(activeEid && window.isEditMode) {{
                        setTimeout(() => {{
                            var el = document.querySelector('[data-editor-id="'+activeEid+'"]');
                            if(el) {{ 
                                el.classList.add('editor-highlight');
                                var rect = el.getBoundingClientRect();
                                if(rect.top < 0 || rect.bottom > window.innerHeight) {{
                                    el.scrollIntoView({{behavior: 'instant', block: 'center'}});
                                }}
                            }}
                        }}, 50);
                    }}
                }});
            }})();
        """
        
        js = js.replace("</script>", f"{scroll_fix_js}\n        </script>")
        
        html = html.replace("</body>", f"{js}\n</body>") if "</body>" in html else html + js
        
        self.web_view.setHtml(html, QUrl.fromLocalFile(os.path.abspath(self.current_file_path)) if self.current_file_path else QUrl())

    def save_file(self):

        self.kbd_save()

    def _callback_save(self, html):
        self.process_synced_html(html, auto_save=True)

    def _callback_save_as(self, html):
        self.process_synced_html(html, auto_save_as=True)

    def kbd_save(self):
        if not self.current_file_path:
            self.kbd_save_as()
            return
        self.statusBar().showMessage("🔄 Syncing and saving...", 2000)
        self.web_view.page().runJavaScript("document.documentElement.outerHTML", 0, self._callback_save)

    def kbd_save_as(self):
        self.statusBar().showMessage("🔄 Syncing and preparing new save...", 2000)
        self.web_view.page().runJavaScript("document.documentElement.outerHTML", 0, self._callback_save_as)

    def execute_save(self, filepath):
        if not filepath: return
        
        try:
            filepath = os.path.abspath(filepath)
            
            cl_soup = self.parse_html(str(self.soup))
            for t in cl_soup.find_all(True):
                if 'data-editor-id' in t.attrs: del t['data-editor-id']
                if 'data-locked' in t.attrs: del t['data-locked']
                if 'class' in t.attrs and 'editor-highlight' in t['class']:
                    t['class'].remove('editor-highlight')
                    if not t['class']: del t['class']
            
            head = cl_soup.find('head')
            if not head:
                head = cl_soup.new_tag('head')
                if cl_soup.html: cl_soup.html.insert(0, head)
                
            if not cl_soup.find(id='miniapp-base-css'):
                base_css = cl_soup.new_tag('style', id='miniapp-base-css')
                base_css.string = "\n        * { box-sizing: border-box; }\n        img, video, iframe { max-width: 100%; height: auto; object-fit: contain; }\n        p, h1, h2, h3, h4, h5, h6, span, div, a { max-width: 100%; overflow-wrap: break-word; }\n        html, body { overflow-x: hidden; }\n    "
                head.append(base_css)
                
            if not cl_soup.find(id='miniapp-nav-script'):
                nav_js = cl_soup.new_tag('script', id='miniapp-nav-script')
                nav_js.string = """
        document.addEventListener('DOMContentLoaded', function() {
            var pageIds = [];
            document.querySelectorAll('[data-trang]').forEach(function(btn) {
                var tId = btn.getAttribute('data-trang');
                if (tId && pageIds.indexOf(tId) === -1) pageIds.push(tId);
            });
            document.body.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-trang]');
                if (btn) {
                    var targetId = btn.getAttribute('data-trang');
                    var targetPage = document.getElementById(targetId);
                    if (targetPage) {
                        e.preventDefault();
                        pageIds.forEach(function(id) {
                            var p = document.getElementById(id);
                            if (p) {
                                p.classList.remove('trang-dang-hien-thi');
                                p.style.setProperty('display', 'none', 'important');
                            }
                        });
                        targetPage.classList.add('trang-dang-hien-thi');
                        targetPage.style.setProperty('display', 'block', 'important');
                        
                        document.querySelectorAll('[data-trang]').forEach(function(b) {
                            b.classList.remove('menu-dang-chon');
                        });
                        document.querySelectorAll('[data-trang="' + targetId + '"]').forEach(function(ab){ 
                            ab.classList.add('menu-dang-chon'); 
                        });
                    }
                }
            });
        });
    """
                if cl_soup.body: cl_soup.body.append(nav_js)
            
            pretty_html = cl_soup.prettify()
            
            with open(filepath, 'w', encoding='utf-8') as f: 
                f.write(pretty_html)
            
            self.statusBar().showMessage(f"💾 Saved successfully: {os.path.basename(filepath)}", 5000)
            QMessageBox.information(self, "Success", f"Saved and embedded standalone navigation script!\n\n📍 Actual path:\n{filepath}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error Saving File", f"The system refused write permission:\n{str(e)}")

    def execute_save_as(self):
        default_dir = os.path.dirname(self.current_file_path) if self.current_file_path else BASE_DIR
        path, _ = QFileDialog.getSaveFileName(self, "Save as New File (Save As)", default_dir, "HTML (*.html *.htm)")
        
        if path:
            
            if not path.lower().endswith('.html') and not path.lower().endswith('.htm'):
                path += '.html'
                
            self.current_file_path = os.path.abspath(path)
            self.lbl_current_file.setText(f"Viewing: <b>{os.path.basename(self.current_file_path)}</b>")
            self.execute_save(self.current_file_path)

    def create_blank_page(self, theme="light"):
        import datetime
        self.save_state_for_undo()
        
        new_dir = os.path.join(BASE_DIR, "New_html")
        os.makedirs(new_dir, exist_ok=True)
        
        existing_files = [f for f in os.listdir(new_dir) if f.lower().endswith('.html')]
        idx = len(existing_files) + 1
        
        date_str = datetime.datetime.now().strftime("%d%m%Y")
        filename = f"{idx:04d}_{date_str}_{theme}.html"
        filepath = os.path.join(new_dir, filename)

        if theme == "dark":
            bg_body = "#121212"
            text_color = "#e0e0e0"
        else:
            bg_body = "#f5f5f5"
            text_color = "#333333"

        
        blank_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>New Page ({theme.upper()})</title>
</head>
<body style="min-height: 100vh; margin: 0; padding: 20px; font-family: sans-serif; background-color: {bg_body}; color: {text_color}; box-sizing: border-box;">
</body>
</html>"""

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(blank_html)
                
            self.current_file_path = filepath
            self.lbl_current_file.setText(f"Viewing: <b>{filename}</b>")
            self.soup = self.parse_html(blank_html)
            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage(f"📄 Created a 100% blank {theme} page (No more placeholder containers): {filename}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error creating page", f"Could not create page:\n{str(e)}")


    def create_dashboard_page(self, theme="dark"):
        import datetime
        self.save_state_for_undo()
        
        if theme == "dark":
            bg_body = "#0f111a"
            text_color = "#ffffff"
            sidebar_html = '<div class="sidebar" style="width: 250px; background: #161925; border-right: 1px solid #232736; display: flex; flex-direction: column; padding: 20px 0; flex-shrink: 0;"><div class="logo" style="text-align: center; margin-bottom: 30px;"><img src="https://via.placeholder.com/80" style="border-radius: 10px; margin-bottom: 10px;"><h2 style="margin: 0; color: #00d2ff; font-size: 20px;">MyApp</h2></div><div class="menu-group" style="padding: 0 20px; margin-bottom: 15px;"><div style="font-size: 12px; color: #666; margin-bottom: 10px; text-transform: uppercase;">Main Menu</div><a href="#" style="display: block; padding: 12px 15px; background: rgba(0,210,255,0.1); color: #00d2ff; border-radius: 8px; text-decoration: none; margin-bottom: 5px; border-left: 3px solid #00d2ff;">🚀 Overview</a><a href="#" style="display: block; padding: 12px 15px; color: #aaa; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">📁 Management</a><a href="#" style="display: block; padding: 12px 15px; color: #aaa; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">⚙️ Settings</a></div></div>' 
            layout_style = "display: flex; min-height: 100vh; width: 100%; background: #0f111a; color: #fff; font-family: sans-serif;"
            main_style = "flex: 1; padding: 30px; display: flex; flex-direction: column; background: #0f111a; overflow-y: auto;"
        else:
            bg_body = "#f4f6f8"
            text_color = "#333333"
            sidebar_html = '<div class="sidebar" style="width: 250px; background: #ffffff; border-right: 1px solid #e0e0e0; display: flex; flex-direction: column; padding: 20px 0; flex-shrink: 0;"><div class="logo" style="text-align: center; margin-bottom: 30px;"><img src="https://via.placeholder.com/80" style="border-radius: 10px; margin-bottom: 10px;"><h2 style="margin: 0; color: #007acc; font-size: 20px;">MyApp</h2></div><div class="menu-group" style="padding: 0 20px; margin-bottom: 15px;"><div style="font-size: 12px; color: #888; margin-bottom: 10px; text-transform: uppercase;">Main Menu</div><a href="#" style="display: block; padding: 12px 15px; background: rgba(0,122,204,0.1); color: #007acc; border-radius: 8px; text-decoration: none; margin-bottom: 5px; border-left: 3px solid #007acc;">🚀 Overview</a><a href="#" style="display: block; padding: 12px 15px; color: #555; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">📁 Management</a><a href="#" style="display: block; padding: 12px 15px; color: #555; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">⚙️ Settings</a></div></div>' 
            layout_style = "display: flex; min-height: 100vh; width: 100%; background: #f4f6f8; color: #333; font-family: sans-serif;"
            main_style = "flex: 1; padding: 30px; display: flex; flex-direction: column; background: #f4f6f8; overflow-y: auto;"

        body = self.soup.find('body') if self.soup else None
        has_content = False
        if body:
            real_tags = [c for c in body.children if isinstance(c, Tag) and c.name not in ['script', 'style', 'link', 'meta']]
            if len(real_tags) > 0:
                has_content = True

        if has_content:
            if self.soup.find(class_='dashboard-layout') or self.soup.find(class_='sidebar'):
                QMessageBox.warning(self, "Notice", "The current page already has a Sidebar/Dashboard structure, cannot wrap again!")
                return

            dashboard_node = self.soup.new_tag('div')
            dashboard_node['class'] = "dashboard-layout"
            dashboard_node['style'] = layout_style

            sidebar_soup = self.parse_html(sidebar_html)
            sidebar_node = sidebar_soup.find(class_='sidebar')

            main_node = self.soup.new_tag('div')
            main_node['class'] = "main-content"
            main_node['style'] = main_style

            for child in list(body.contents):
                if isinstance(child, Tag) and child.name in ['script', 'style'] and 'mini-app' in str(child.get('id', '')):
                    continue # Skip past the Editor script
                main_node.append(child.extract())

            dashboard_node.append(sidebar_node)
            dashboard_node.append(main_node)
            body.append(dashboard_node)

            body['style'] = f"min-height: 100vh; margin: 0; padding: 0; font-family: sans-serif; background-color: {bg_body}; color: {text_color}; overflow-x: hidden;"

            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage("🎛️ Current content successfully wrapped with a Dashboard structure!", 5000)

        else:
            new_dir = os.path.join(BASE_DIR, "New_html")
            os.makedirs(new_dir, exist_ok=True)
            
            existing_files = [f for f in os.listdir(new_dir) if f.lower().endswith('.html')]
            idx = len(existing_files) + 1
            
            date_str = datetime.datetime.now().strftime("%d%m%Y")
            filename = f"{idx:04d}_{date_str}_Dashboard_{theme.capitalize()}.html"
            filepath = os.path.join(new_dir, filename)

            dashboard_html_full = f'<div class="dashboard-layout" style="{layout_style}">{sidebar_html}<div class="main-content" style="{main_style}"></div></div>'
            full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Dashboard {theme.capitalize()}</title>
</head>
<body style="min-height: 100vh; margin: 0; padding: 0; font-family: sans-serif; background-color: {bg_body}; color: {text_color}; overflow-x: hidden;">
{dashboard_html_full}
</body>
</html>"""

            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(full_html)
                    
                self.current_file_path = filepath
                self.lbl_current_file.setText(f"Viewing: <b>{filename}</b>")
                self.soup = self.parse_html(full_html)
                self.refresh_tree()
                self.update_preview()
                self.statusBar().showMessage(f"🎛️ Auto-generated Dashboard: {filename}", 5000)
            except Exception as e:
                QMessageBox.critical(self, "Error creating page", f"Could not create page:\n{str(e)}")

    def export_project_to_zip(self):
        if not self.current_file_path:
            QMessageBox.warning(self, "Warning", "Please open or save the project as an HTML file before exporting a ZIP.")
            return

        zip_path, _ = QFileDialog.getSaveFileName(self, "Export Project to ZIP file", os.path.dirname(self.current_file_path), "ZIP Archive (*.zip)")
        if not zip_path: return

        self.statusBar().showMessage("📦 Collecting assets and packaging ZIP...", 2000)
        
        try:
            base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
            
            with tempfile.TemporaryDirectory() as temp_dir:
                assets_dir = os.path.join(temp_dir, "assets")
                os.makedirs(assets_dir, exist_ok=True)
                
                export_soup = self.parse_html(str(self.soup))
                
                for t in export_soup.find_all(True):
                    if 'data-editor-id' in t.attrs: del t['data-editor-id']
                    if 'data-locked' in t.attrs: del t['data-locked']
                    if 'class' in t.attrs and 'editor-highlight' in t['class']:
                        t['class'].remove('editor-highlight')
                        if not t['class']: del t['class']
                
                for s_id in ["mini-app-editor-script", "mini-app-editor-style"]:
                    s = export_soup.find(id=s_id)
                    if s: s.decompose()
                    
                head = export_soup.find('head')
                if not head:
                    head = export_soup.new_tag('head')
                    if export_soup.html: export_soup.html.insert(0, head)
                if not export_soup.find(id='miniapp-base-css'):
                    base_css = export_soup.new_tag('style', id='miniapp-base-css')
                    base_css.string = "\n        * { box-sizing: border-box; }\n        img, video, iframe { max-width: 100%; height: auto; object-fit: contain; }\n        p, h1, h2, h3, h4, h5, h6, span, div, a { max-width: 100%; overflow-wrap: break-word; }\n        html, body { overflow-x: hidden; }\n    "
                    head.append(base_css)

                if not export_soup.find(id='miniapp-nav-script'):
                    nav_js = export_soup.new_tag('script', id='miniapp-nav-script')
                    nav_js.string = """
        document.addEventListener('DOMContentLoaded', function() {
            var pageIds = [];
            document.querySelectorAll('[data-trang]').forEach(function(btn) {
                var tId = btn.getAttribute('data-trang');
                if (tId && pageIds.indexOf(tId) === -1) pageIds.push(tId);
            });
            document.body.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-trang]');
                if (btn) {
                    var targetId = btn.getAttribute('data-trang');
                    var targetPage = document.getElementById(targetId);
                    if (targetPage) {
                        e.preventDefault();
                        pageIds.forEach(function(id) {
                            var p = document.getElementById(id);
                            if (p) {
                                p.classList.remove('trang-dang-hien-thi');
                                p.style.setProperty('display', 'none', 'important');
                            }
                        });
                        targetPage.classList.add('trang-dang-hien-thi');
                        targetPage.style.setProperty('display', 'block', 'important');
                        
                        document.querySelectorAll('[data-trang]').forEach(function(b) {
                            b.classList.remove('menu-dang-chon');
                        });
                        document.querySelectorAll('[data-trang="' + targetId + '"]').forEach(function(ab){ 
                            ab.classList.add('menu-dang-chon'); 
                        });
                    }
                }
            });
        });
    """
                    if export_soup.body: export_soup.body.append(nav_js)

                for tag in export_soup.find_all(['img', 'video', 'audio', 'source', 'link', 'script', 'a']):
                    attr = 'src' if tag.has_attr('src') else 'href' if tag.has_attr('href') else None
                    if attr and tag[attr]:
                        src_val = str(tag[attr])
                        # Skip web links or base64
                        if not src_val.startswith(('http://', 'https://', 'data:', '//', '#')):
                            clean_src = urllib.parse.unquote(src_val)
                            local_filepath = os.path.normpath(os.path.join(base_dir, clean_src))
                            
                            if os.path.exists(local_filepath) and os.path.isfile(local_filepath):
                                filename = os.path.basename(local_filepath)

                                new_filename = filename
                                counter = 1
                                while os.path.exists(os.path.join(assets_dir, new_filename)):
                                    name, ext = os.path.splitext(filename)
                                    new_filename = f"{name}_{counter}{ext}"
                                    counter += 1
                                    
                                shutil.copy2(local_filepath, os.path.join(assets_dir, new_filename))
                                tag[attr] = f"assets/{new_filename}"

                html_path = os.path.join(temp_dir, "index.html")
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(export_soup.prettify())
                    
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(html_path, arcname="index.html")
                    for root, _, files in os.walk(assets_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_name = os.path.join("assets", os.path.relpath(file_path, assets_dir)).replace('\\', '/')
                            zipf.write(file_path, arcname=arc_name)

            self.statusBar().showMessage(f"✅ Packaging complete: {os.path.basename(zip_path)}", 5000)
            QMessageBox.information(self, "ZIP Export Successful", f"The entire project has been packaged at:\n{zip_path}\n\nAll local images and libraries have been neatly gathered into the 'assets/' folder.")

        except Exception as e:
            QMessageBox.critical(self, "Packaging Error", f"The ZIP export process was interrupted:\n{str(e)}")

    def export_production_zip(self):
        if not self.current_file_path:
            QMessageBox.warning(self, "Warning", "Please open or save the project as an HTML file before exporting Production.")
            return

        zip_path, _ = QFileDialog.getSaveFileName(self, "Export Production (Cleanly split Inline CSS & Optimize)", os.path.dirname(self.current_file_path), "ZIP Archive (*.zip)")
        if not zip_path: return

        self.statusBar().showMessage("🚀 Running the CSS-extraction and source optimization Engine...", 2000)
        
        try:
            base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
            
            with tempfile.TemporaryDirectory() as temp_dir:
                assets_dir = os.path.join(temp_dir, "assets")
                css_dir = os.path.join(temp_dir, "css")
                os.makedirs(assets_dir, exist_ok=True)
                os.makedirs(css_dir, exist_ok=True)
                
                export_soup = self.parse_html(str(self.soup))
                
                for t in export_soup.find_all(True):
                    if 'data-editor-id' in t.attrs: del t['data-editor-id']
                    if 'data-locked' in t.attrs: del t['data-locked']
                    if 'class' in t.attrs and 'editor-highlight' in t['class']:
                        t['class'].remove('editor-highlight')
                        if not t['class']: del t['class']
                
                for s_id in ["mini-app-editor-script", "mini-app-editor-style"]:
                    s = export_soup.find(id=s_id)
                    if s: s.decompose()
                    
                if not export_soup.find(id='miniapp-nav-script'):
                    nav_js = export_soup.new_tag('script', id='miniapp-nav-script')
                    nav_js.string = """
        document.addEventListener('DOMContentLoaded', function() {
            var pageIds = [];
            document.querySelectorAll('[data-trang]').forEach(function(btn) {
                var tId = btn.getAttribute('data-trang');
                if (tId && pageIds.indexOf(tId) === -1) pageIds.push(tId);
            });
            document.body.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-trang]');
                if (btn) {
                    var targetId = btn.getAttribute('data-trang');
                    var targetPage = document.getElementById(targetId);
                    if (targetPage) {
                        e.preventDefault();
                        pageIds.forEach(function(id) {
                            var p = document.getElementById(id);
                            if (p) {
                                p.classList.remove('trang-dang-hien-thi');
                                p.style.setProperty('display', 'none', 'important');
                            }
                        });
                        targetPage.classList.add('trang-dang-hien-thi');
                        targetPage.style.setProperty('display', 'block', 'important');
                        
                        document.querySelectorAll('[data-trang]').forEach(function(b) {
                            b.classList.remove('menu-dang-chon');
                        });
                        document.querySelectorAll('[data-trang="' + targetId + '"]').forEach(function(ab){ 
                            ab.classList.add('menu-dang-chon'); 
                        });
                    }
                }
            });
        });
    """
                    if export_soup.body: export_soup.body.append(nav_js)
                    
                style_map = {}
                css_rules = [
                    "/* Optimized by Universal No-Code Designer */",
                    "* { box-sizing: border-box; }",
                    "img, video, iframe { max-width: 100%; height: auto; object-fit: contain; }",
                    "p, h1, h2, h3, h4, h5, h6, span, div, a { max-width: 100%; overflow-wrap: break-word; }",
                    "html, body { overflow-x: hidden; }\n"
                ]
                class_counter = 1
                
                for tag in export_soup.find_all(True):
                    st = tag.get('style')
                    if st and isinstance(st, str):
                        st = st.replace('\n', ' ').strip()
                        if st.endswith(';'): st = st[:-1]
                        st = st.strip()
                        
                        if st:

                            if st not in style_map:
                                cls_name = f"opt-ui-{class_counter:04d}"
                                style_map[st] = cls_name
                                css_rules.append(f".{cls_name} {{ {st} !important; }}")
                                class_counter += 1
                            

                            target_cls = style_map[st]
                            current_classes = tag.get('class', [])
                            if isinstance(current_classes, str): current_classes = [current_classes]
                            current_classes.append(target_cls)
                            tag['class'] = current_classes
                            del tag['style']
                

                prod_css_path = os.path.join(css_dir, "style.min.css")
                with open(prod_css_path, 'w', encoding='utf-8') as f:
                    f.write("\n".join(css_rules))
                

                head = export_soup.find('head')
                if not head:
                    head = export_soup.new_tag('head')
                    if export_soup.html: export_soup.html.insert(0, head)
                
                link_css = export_soup.new_tag('link', rel='stylesheet', href='css/style.min.css')
                head.append(link_css)
                        

                for tag in export_soup.find_all(['img', 'video', 'audio', 'source', 'link', 'script', 'a']):
                    attr = 'src' if tag.has_attr('src') else 'href' if tag.has_attr('href') else None
                    if attr and tag[attr]:
                        src_val = str(tag[attr])
                        if not src_val.startswith(('http://', 'https://', 'data:', '//', '#')):
                            clean_src = urllib.parse.unquote(src_val)
                            local_filepath = os.path.normpath(os.path.join(base_dir, clean_src))
                            
                            if os.path.exists(local_filepath) and os.path.isfile(local_filepath):
                                filename = os.path.basename(local_filepath)
                                new_filename = filename
                                counter = 1
                                while os.path.exists(os.path.join(assets_dir, new_filename)):
                                    name, ext = os.path.splitext(filename)
                                    new_filename = f"{name}_{counter}{ext}"
                                    counter += 1
                                    
                                shutil.copy2(local_filepath, os.path.join(assets_dir, new_filename))
                                tag[attr] = f"assets/{new_filename}"


                html_path = os.path.join(temp_dir, "index.html")
                raw_minified_html = str(export_soup)
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(raw_minified_html)
                    

                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(html_path, arcname="index.html")
                    zipf.write(prod_css_path, arcname="css/style.min.css")
                    for root, _, files in os.walk(assets_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_name = os.path.join("assets", os.path.relpath(file_path, assets_dir)).replace('\\', '/')
                            zipf.write(file_path, arcname=arc_name)

            self.statusBar().showMessage(f"🚀 Production export complete: {os.path.basename(zip_path)}", 5000)
            QMessageBox.information(self, "Optimization Successful", f"An ultra-lightweight Website structure has been exported!\n\nAll Inline-CSS has been extracted and neatly grouped into the 'css/style.min.css' folder.\nYou can confidently drop this file onto your Host.")

        except Exception as e:
            QMessageBox.critical(self, "Packaging Error", f"The Production export process was interrupted:\n{str(e)}")

    def setup_quick_components_ui(self, layout):
        row1 = QHBoxLayout(); row1.setContentsMargins(0,0,0,0)
        row2 = QHBoxLayout(); row2.setContentsMargins(0,0,0,5)
        row3 = QHBoxLayout(); row3.setContentsMargins(0,5,0,10) 
        
        def load_templates(file_name, fallback_dict):
            try:
                file_path = os.path.join(BASE_DIR, file_name)
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "items" in data:
                            new_dict = {}
                            for item in data["items"]:
                                name = item.get("name")
                                html = item.get("html")
                                if name and html:
                                    new_dict[name] = html
                            if new_dict: return new_dict
            except Exception as e:
                print(f"⚠️ Error loading data from {file_name}: {e}")
            return fallback_dict

        def create_dropdown_btn(title, tpl_dict):
            btn = QPushButton(title)
            btn.setStyleSheet("background:#333; border:1px solid #555; padding:6px; border-radius:4px; font-size:12px; font-weight:bold;")
            menu = QMenu(btn)
            menu.setStyleSheet("QMenu { background:#252526; color:white; border:1px solid #3e3e42; } QMenu::item { padding: 5px 20px; } QMenu::item:selected {background:#094771;}")
            
            for label, html in tpl_dict.items():
                menu.addAction(label).triggered.connect(lambda *args, v=html: self.insert_quick_component(v))
                    
            btn.setMenu(menu)
            return btn

        bz = "background: rgba(150,150,150,0.05); border: 1px solid rgba(150,150,150,0.3); color: inherit; padding: 15px; border-radius: 8px; overflow: hidden;"
        
        fb_layout = {
            "🔲 2 Equal Columns (1/2 - 1/2)": f'<div class="row-wrap" style="display:flex;flex-wrap:wrap;gap:15px;width:100%;"><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Left Column (1/2)</div><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Right Column (1/2)</div></div>',
            "🔲 3 Equal Columns (1/3 - 1/3 - 1/3)": f'<div class="row-wrap" style="display:flex;flex-wrap:wrap;gap:15px;width:100%;"><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Column 1 (1/3)</div><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Column 2 (1/3)</div><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Column 3 (1/3)</div></div>',
            "🔲 Left Weighted (1/3 - 2/3)": f'<div class="row-wrap" style="display:flex;flex-wrap:wrap;gap:15px;width:100%;"><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Left (1/3)</div><div class="col" style="flex:2 1 0%;min-width:250px;max-width:100%;{bz}">Right (2/3)</div></div>',
            "🔲 Right Weighted (2/3 - 1/3)": f'<div class="row-wrap" style="display:flex;flex-wrap:wrap;gap:15px;width:100%;"><div class="col" style="flex:2 1 0%;min-width:250px;max-width:100%;{bz}">Left (2/3)</div><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Right (1/3)</div></div>' 
        }
        fb_table = { "📊 Basic Data Table": '<div style="overflow-x:auto;padding:10px;width:100%;"><table style="width:100%;border-collapse:collapse;margin:15px 0;font-family:sans-serif;color:inherit;"><tr style="background:#007acc;color:white;text-align:left;"><th style="padding:12px 15px;">ID</th><th style="padding:12px 15px;">Full Name</th><th style="padding:12px 15px;">Status</th></tr><tr style="border-bottom: 1px solid rgba(150,150,150,0.3);"><td style="padding:12px 15px;">#01</td><td style="padding:12px 15px;">John Smith</td><td style="padding:12px 15px;"><span style="background:#28a745;color:white;padding:4px 8px;border-radius:12px;font-size:12px;">Active</span></td></tr></table></div>' }
        fb_button = { "🔘 Button (Basic Btn)": '<a href="#" style="display:inline-block;background:#007acc;color:#fff;padding:10px 25px;border-radius:25px;text-decoration:none;font-weight:bold;box-shadow:0 4px 6px rgba(0,122,204,0.3); transition: 0.3s;margin:5px;">Click Here</a>' }
        
        card_html = '<div class="card" style="flex:1 1 0%;min-width:200px;max-width:100%;display:flex;flex-direction:column;border:1px solid rgba(150,150,150,0.3);background:rgba(150,150,150,0.02);color:inherit;border-radius:10px;overflow:hidden;box-shadow: 0 4px 8px rgba(0,0,0,0.1);"><div style="height:150px;background:rgba(0,0,0,0.2);display:flex;align-items:center;justify-content:center;padding:10px;border-bottom:1px solid rgba(150,150,150,0.2);"><img src="https://via.placeholder.com/150" style="max-height:100%;max-width:100%;object-fit:contain;"></div><div style="padding:15px;display:flex;flex-direction:column;flex:1;"><h3 style="margin:0 0 10px 0;font-size:18px;">Card Title</h3><p style="font-size:14px;line-height:1.5;opacity:0.8;margin:0 0 15px 0;">Card content description.</p><a href="#" style="display:block;padding:10px;background:#007bff;color:white;text-decoration:none;border-radius:5px;text-align:center;margin-top:auto;font-weight:bold;">Details</a></div></div>' 
        card_large = card_html.replace('flex:1 1 0%;', 'flex:2 1 0%;').replace('min-width:200px;', 'min-width:300px;')
        card_1_large_2_small = (
            '<div style="display:flex;flex-wrap:wrap;gap:20px;width:100%;margin:15px 0;">'
                '<div style="flex:1 1 300px;border:1px solid rgba(255,255,255,0.2);border-radius:8px;'
                'display:flex;align-items:flex-start;justify-content:flex-start;min-height:180px;'
                'background:rgba(20,20,25,1);padding:15px;">'
                    '<div style="display:flex;align-items:center;gap:10px;">'
                        '<img src="https://via.placeholder.com/20" style="width:20px;height:20px;object-fit:cover;">'
                        '<span style="color:#fff;font-family:sans-serif;font-size:14px;">Modules T2SPP</span>'
                    '</div>'
                '</div>'
                '<div style="flex:1 1 300px;display:flex;flex-direction:column;gap:15px;justify-content:center;">'
                    '<div style="display:flex;align-items:center;justify-content:space-between;background:#1a1c23;'
                    'border:1px solid rgba(255,255,255,0.1);padding:15px 20px;border-radius:8px;">'
                        '<div style="font-weight:bold;color:#00d2ff;font-family:sans-serif;">👩 Female Voice</div>' 
                        '<a href="#" style="padding:8px 20px;background:transparent;color:#00d2ff;text-decoration:none;'
                        'border:1px solid #00d2ff;border-radius:5px;font-size:13px;font-weight:bold;">Download</a>' 
                    '</div>'
                    '<div style="display:flex;align-items:center;justify-content:space-between;background:#1a1c23;'
                    'border:1px solid rgba(255,255,255,0.1);padding:15px 20px;border-radius:8px;">'
                        '<div style="font-weight:bold;color:#00d2ff;font-family:sans-serif;">👨 Male Voice</div>' 
                        '<a href="#" style="padding:8px 20px;background:transparent;color:#00d2ff;text-decoration:none;'
                        'border:1px solid #00d2ff;border-radius:5px;font-size:13px;font-weight:bold;">Download</a>' 
                    '</div>'
                '</div>'
            '</div>'
        )

        card_profile = (
            '<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(150,150,150,0.2);'
            'border-radius:12px;padding:20px;text-align:center;width:100%;max-width:280px;margin:15px auto;'
            'box-shadow:0 4px 10px rgba(0,0,0,0.1);">'
                '<img src="https://via.placeholder.com/100" style="width:80px;height:80px;border-radius:50%;'
                'object-fit:cover;border:3px solid #00d2ff;margin-bottom:15px;">'
                '<h3 style="margin:0 0 5px 0;font-size:18px;color:#fff;">John Doe</h3>' 
                '<p style="margin:0 0 15px 0;font-size:13px;color:#888;">UI/UX Specialist</p>' 
                '<div style="display:flex;gap:10px;justify-content:center;">'
                    '<a href="#" style="padding:6px 12px;background:#00d2ff;color:#000;text-decoration:none;'
                    'border-radius:20px;font-size:12px;font-weight:bold;">Follow</a>' 
                    '<a href="#" style="padding:6px 12px;background:transparent;color:#00d2ff;'
                    'border:1px solid #00d2ff;text-decoration:none;border-radius:20px;font-size:12px;'
                    'font-weight:bold;">Message</a>' 
                '</div>'
            '</div>'
        )

        card_feature = (
            '<div style="flex:1 1 250px;background:#1a1c23;border-top:4px solid #ff007f;border-radius:8px;'
            'padding:25px;margin:15px;box-shadow:0 5px 15px rgba(0,0,0,0.2);transition:0.3s;">'
                '<div style="font-size:30px;margin-bottom:15px;">⚡</div>'
                '<h3 style="margin:0 0 10px 0;color:#fff;font-size:18px;">Speed Optimization</h3>' 
                '<p style="color:#aaa;font-size:14px;line-height:1.6;margin:0 0 20px 0;">The system is designed ' 
                'to render extremely fast, giving end users a smooth experience.</p>'
                '<a href="#" style="color:#ff007f;text-decoration:none;font-weight:bold;font-size:13px;">'
                'Explore now ➔</a>'
            '</div>'
        )

        card_alert = (
            '<div style="display:flex;align-items:flex-start;gap:15px;background:rgba(255,193,7,0.1);'
            'border-left:4px solid #ffc107;padding:15px 20px;border-radius:0 8px 8px 0;margin:15px 0;width:100%;">'
                '<div style="font-size:24px;">🔔</div>'
                '<div>'
                    '<h4 style="margin:0 0 5px 0;color:#ffc107;font-size:16px;">Important Note</h4>' 
                    '<p style="margin:0;color:#ddd;font-size:14px;line-height:1.5;">Please back up your data ' 
                    'before updating to the new version to avoid data loss.</p>'
                '</div>'
            '</div>'
        )

        fb_card = {
            "1 Standalone Card": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}</div>',
            "2 Cards side by side (1/2 - 1/2)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}{card_html}</div>',
            "3 Cards side by side (1/3 - 1/3 - 1/3)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}{card_html}{card_html}</div>',
            "2 Weighted Cards (Small 1/3 - Large 2/3)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}{card_large}</div>',
            "2 Weighted Cards (Large 2/3 - Small 1/3)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_large}{card_html}</div>',
            "🌟 Horizontal Card (Image Left - Text Right)": '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:20px;border:1px solid #333;background:rgba(255,255,255,0.03);padding:20px;border-radius:12px;width:100%;margin:15px 0;"><div style="flex:0 0 140px;height:120px;display:flex;align-items:center;justify-content:center;"><img src="https://via.placeholder.com/150" style="max-height:100%;max-width:100%;object-fit:contain;border-radius:10px;"></div><div style="flex:1 1 0%;min-width:200px;display:flex;flex-direction:column;"><h3 style="margin:0 0 10px 0;font-size:20px;color:#00d2ff;">App Tool Name</h3><p style="font-size:14px;line-height:1.6;color:#bbb;margin:0 0 15px 0;">Standard Media Object Card.</p><a href="#" style="align-self:flex-start;padding:10px 24px;background:#00bcd4;color:#fff;text-decoration:none;border-radius:8px;font-weight:bold;font-size:13px;">Download</a></div></div>',
            "📦 1 Large (Left) - 2 Small (Right)": card_1_large_2_small,
            "👤 Profile Card (User Profile)": card_profile,
            "🚀 Feature Card": card_feature,
            "⚠️ Alert / Notice Card": card_alert
        }
        
        fb_header = { "Header (Original)": '<header style="background:inherit;color:inherit;padding:15px 30px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(150,150,150,0.3);width:100%;"><div style="font-size:24px;font-weight:bold;color:#007acc;">🚀 MyLogo</div><nav style="display:flex;gap:20px;"><a href="#" style="color:inherit;text-decoration:none;font-weight:500;">Home</a></nav></header>' }
        fb_footer = {
            "Template 1: Simple & Centered": '<footer style="background:rgba(0,0,0,0.8);color:#fff;padding:30px 20px;text-align:center;margin-top:20px;width:100%;"><h3 style="margin-bottom:10px;">Connect With Us</h3><p style="margin-bottom:15px;font-size:14px;">Address: 123 Main Street, Ho Chi Minh City</p></footer>',
            "Template 2: Detailed columns & QR code": '<footer style="background:rgba(0,0,0,0.85);color:#fff;padding:40px 20px;font-family:sans-serif;margin-top:20px;width:100%;"><div style="display:flex;flex-wrap:wrap;gap:30px;max-width:1000px;margin:0 auto;justify-content:space-between;"><div style="flex:1 1 0%;min-width:250px;max-width:100%;"><h3 style="color:#007acc;margin-top:0;">MyLogo</h3><p style="font-size:14px;color:#bbb;line-height:1.6;">A great solution.</p></div><div style="flex:1 1 0%;min-width:150px;max-width:100%;text-align:center;"><h4 style="margin-top:0;">Scan Zalo</h4><img src="https://via.placeholder.com/100" style="width:100px;"></div></div></footer>' 
        }

        fb_margin = {
            "📐 Standard Box Margin (Max 1200px - Centered)": '<div class="container-box" style="max-width:1200px; margin:0 auto; padding:0 15px; width:100%; box-sizing:border-box;"><div style="border:1px dashed #555; padding:20px; text-align:center; opacity:0.6;">1200px Container</div></div>',
            "📐 Article Margin (Max 800px - Centered)": '<div class="container-article" style="max-width:800px; margin:0 auto; padding:0 15px; width:100%; box-sizing:border-box;"><div style="border:1px dashed #555; padding:20px; text-align:center; opacity:0.6;">800px Container</div></div>',
            "📐 Left-Aligned Margin (Indented)": '<div class="container-left" style="margin-left:5%; padding-left:20px; border-left:3px solid #007acc; width:95%; box-sizing:border-box;"><div style="padding:10px; opacity:0.6;">Left-aligned container</div></div>',
            "📐 Full-Bleed Margin (With Padding)": '<div class="container-fluid" style="width:100%; padding:20px; box-sizing:border-box;"><div style="border:1px dashed #555; padding:20px; text-align:center; opacity:0.6;">Full-bleed container</div></div>' 
        }
        
        fb_divider = {
            "➖ Horizontal Rule (Bold)": '<hr style="border:none; border-top:2px solid rgba(150,150,150,0.5); margin:20px 0; width:100%;">',
            "➖ Horizontal Rule (Faded / Dashed)": '<hr style="border:none; border-top:1px dashed rgba(150,150,150,0.3); margin:20px 0; width:100%;">',
            "📏 Spacer (20px)": '<div class="spacer" style="height:20px; width:100%; clear:both;"></div>',
            "📏 Spacer (50px)": '<div class="spacer" style="height:50px; width:100%; clear:both;"></div>' 
        }

        fb_form = {
            "📝 Contact Form (Formspree)": (
                '<form action="https://formspree.io/f/MAY_BE_YOUR_API" method="POST" '
                'style="background:rgba(255,255,255,0.02); padding:20px; border-radius:8px; '
                'border:1px solid #444; max-width:500px; margin:0 auto; width:100%; '
                'font-family:sans-serif; color:inherit;">'
                '<h3 style="margin-top:0; color:#00d2ff; margin-bottom:20px; font-size: 22px;">Contact Us</h3>' 
                '<div style="margin-bottom:15px;">'
                '<label style="display:block; margin-bottom:5px; font-size:14px; opacity:0.8;">Full Name</label>' 
                '<input type="text" name="name" required style="width:100%; padding:10px; '
                'border-radius:4px; border:1px solid #555; background:rgba(0,0,0,0.2); '
                'color:inherit; box-sizing:border-box;">'
                '</div>'
                '<div style="margin-bottom:15px;">'
                '<label style="display:block; margin-bottom:5px; font-size:14px; opacity:0.8;">Your Email</label>' 
                '<input type="email" name="email" required style="width:100%; padding:10px; '
                'border-radius:4px; border:1px solid #555; background:rgba(0,0,0,0.2); '
                'color:inherit; box-sizing:border-box;">'
                '</div>'
                '<div style="margin-bottom:20px;">'
                '<label style="display:block; margin-bottom:5px; font-size:14px; opacity:0.8;">Message Content</label>' 
                '<textarea name="message" rows="4" required style="width:100%; padding:10px; '
                'border-radius:4px; border:1px solid #555; background:rgba(0,0,0,0.2); '
                'color:inherit; box-sizing:border-box; resize:vertical;"></textarea>'
                '</div>'
                '<button type="submit" style="background:#00d2ff; color:#000; font-weight:bold; '
                'padding:12px 25px; border:none; border-radius:4px; cursor:pointer; width:100%; '
                'font-size:15px; transition:0.3s;">Send Message 🚀</button>' 
                '</form>'
            )
        }
        
        js_tab_switch = "var tId=this.getAttribute('data-trang'); document.querySelectorAll('.trang-noi-dung').forEach(function(el){el.classList.remove('trang-dang-hien-thi'); el.style.display='none';}); var target=document.getElementById(tId); if(target){target.classList.add('trang-dang-hien-thi'); target.style.display='block';} document.querySelectorAll('.nut-chuyen-trang').forEach(function(btn){btn.classList.remove('menu-dang-chon'); if(btn.getAttribute('data-trang')===tId) btn.classList.add('menu-dang-chon');});"

        js_pag_switch = "var p=this.closest('.pagination-wrapper');var act=this.getAttribute('data-action');var pId=this.getAttribute('data-page');var pgs=Array.from(p.querySelectorAll('.phan-trang-noi-dung'));var btns=Array.from(p.querySelectorAll('.nut-phan-trang'));var cIdx=pgs.findIndex(x=>x.style.display==='block');if(cIdx<0)cIdx=0;var nIdx=cIdx;if(act==='first')nIdx=0;if(act==='last')nIdx=pgs.length-1;if(act==='prev')nIdx=Math.max(0,cIdx-1);if(act==='next')nIdx=Math.min(pgs.length-1,cIdx+1);if(pId)nIdx=pgs.findIndex(x=>x.id===pId);if(nIdx<0)return;pgs.forEach((el,i)=>el.style.display=(i===nIdx)?'block':'none');p.querySelectorAll('.pag-dots').forEach(d=>d.remove());var aBg=btns.length>0?(btns[0].getAttribute('data-active-bg')||'#007acc'):'#007acc';btns.forEach((b,i)=>{if(i===nIdx){b.style.background=aBg;b.style.color='#fff';b.style.boxShadow='0 0 10px '+aBg;}else{b.style.background='transparent';b.style.color='inherit';b.style.boxShadow='none';}var disp=b.getAttribute('data-disp')||'inline-block';if(btns.length>5){if(i===0||i===btns.length-1||(i>=nIdx-1&&i<=nIdx+1)){b.style.display=disp;if(i===nIdx-1&&i>1){var d1=document.createElement('span');d1.className='pag-dots';d1.innerHTML='...';d1.style.padding='0 5px';b.parentNode.insertBefore(d1,b);}if(i===btns.length-1&&nIdx<btns.length-3){var d2=document.createElement('span');d2.className='pag-dots';d2.innerHTML='...';d2.style.padding='0 5px';b.parentNode.insertBefore(d2,b);}}else{b.style.display='none';}}else{b.style.display=disp;}});"

        fb_nav = {
            "🔢 Pagination (Square Blocks) - Standalone": f'<div class="pagination-wrapper" style="width:100%; margin:20px 0; border: 1px dashed rgba(150,150,150,0.5); padding: 15px; border-radius: 8px; box-sizing: border-box;"><div id="sub-page-1" class="phan-trang-noi-dung" style="display:block; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#007acc;">Page 1 Content</h3><p style="opacity:0.7;">Drag and drop Text, Table, Image... in here.</p></div><div id="sub-page-2" class="phan-trang-noi-dung" style="display:none; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#007acc;">Page 2 Content</h3><p style="opacity:0.7;">This is page 2.</p></div><div class="pagination" style="display:flex; justify-content:center; align-items:center; gap:8px; width:100%; font-family:sans-serif;"><a class="nav-phan-trang" data-action="first" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&laquo;</a><a class="nav-phan-trang" data-action="prev" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&lsaquo;</a><a class="nut-phan-trang" data-page="sub-page-1" data-active-bg="#007acc" data-disp="inline-block" onclick="{js_pag_switch}" style="padding:8px 15px; background:#007acc; color:#fff; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer; box-shadow:0 0 10px rgba(0,122,204,0.5); border: 1px solid rgba(150,150,150,0.3);">1</a><a class="nut-phan-trang" data-page="sub-page-2" data-active-bg="#007acc" data-disp="inline-block" onclick="{js_pag_switch}" style="padding:8px 15px; background:transparent; color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer; border: 1px solid rgba(150,150,150,0.3);">2</a><a class="nav-phan-trang" data-action="next" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&rsaquo;</a><a class="nav-phan-trang" data-action="last" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&raquo;</a></div></div>',
            
            "🔢 Pagination (Soft Round) - Standalone": f'<div class="pagination-wrapper" style="width:100%; margin:20px 0; border: 1px dashed rgba(150,150,150,0.5); padding: 15px; border-radius: 8px; box-sizing: border-box;"><div id="sub-page-1-rnd" class="phan-trang-noi-dung" style="display:block; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#28a745;">Page 1 Content</h3><p style="opacity:0.7;">Drag and drop Text, Table, Image... in here.</p></div><div id="sub-page-2-rnd" class="phan-trang-noi-dung" style="display:none; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#28a745;">Page 2 Content</h3><p style="opacity:0.7;">This is page 2.</p></div><div class="pagination" style="display:flex; justify-content:center; align-items:center; gap:8px; width:100%; font-family:sans-serif;"><a class="nav-phan-trang" data-action="first" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&laquo;</a><a class="nav-phan-trang" data-action="prev" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&lsaquo;</a><a class="nut-phan-trang" data-page="sub-page-1-rnd" data-active-bg="#28a745" data-disp="flex" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:#28a745; color:#fff; text-decoration:none; border-radius:50%; font-weight:bold; box-shadow:0 0 10px rgba(40,167,69,0.5); cursor:pointer; border: 1px solid rgba(150,150,150,0.3);">1</a><a class="nut-phan-trang" data-page="sub-page-2-rnd" data-active-bg="#28a745" data-disp="flex" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer; border: 1px solid rgba(150,150,150,0.3);">2</a><a class="nav-phan-trang" data-action="next" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&rsaquo;</a><a class="nav-phan-trang" data-action="last" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&raquo;</a></div></div>' 
        }

        row1.addWidget(create_dropdown_btn("🔲 Layout ▼", load_templates("layout.json", fb_layout)))
        row1.addWidget(create_dropdown_btn("📊 Table ▼", load_templates("table.json", fb_table)))
        row1.addWidget(create_dropdown_btn("🖼️ Card ▼", load_templates("card.json", fb_card)))
        
        row2.addWidget(create_dropdown_btn("🔝 Header ▼", load_templates("header.json", fb_header)))
        row2.addWidget(create_dropdown_btn("🔚 Footer ▼", load_templates("footer.json", fb_footer)))
        row2.addWidget(create_dropdown_btn("🔘 Button (Btn) ▼", load_templates("button.json", fb_button)))

        row2.addWidget(create_dropdown_btn("📝 Form ▼", load_templates("form.json", fb_form)))
        row2.addWidget(create_dropdown_btn("🔢 Pagination ▼", load_templates("pagination.json", fb_nav)))
        
        btn_blank = QPushButton("📄 New Page ▼")
        btn_blank.setStyleSheet("background-color: #28a745; color: white; padding: 6px; border-radius: 4px; font-weight: bold;")
        menu_blank = QMenu(btn_blank)
        menu_blank.setStyleSheet("QMenu { background:#252526; color:white; border:1px solid #3e3e42; } QMenu::item { padding: 5px 20px; } QMenu::item:selected {background:#094771;}")
        menu_blank.addAction("🌞 Blank Page (Light Mode)").triggered.connect(lambda: self.create_blank_page("light"))
        menu_blank.addAction("🌙 Dark Page (Dark Mode)").triggered.connect(lambda: self.create_blank_page("dark"))
        btn_blank.setMenu(menu_blank)
        row3.addWidget(btn_blank)

        btn_dash = QPushButton("🎛️ Dashboard ▼")
        btn_dash.setStyleSheet("background-color: #8e44ad; color: white; padding: 6px; border-radius: 4px; font-weight: bold;")
        menu_dash = QMenu(btn_dash)
        menu_dash.setStyleSheet("QMenu { background:#252526; color:white; border:1px solid #3e3e42; } QMenu::item { padding: 5px 20px; } QMenu::item:selected {background:#094771;}")
        menu_dash.addAction("🌙 Dashboard (Dark Mode)").triggered.connect(lambda: self.create_dashboard_page("dark"))
        menu_dash.addAction("🌞 Dashboard (Light Mode)").triggered.connect(lambda: self.create_dashboard_page("light"))
        btn_dash.setMenu(menu_dash)
        row3.addWidget(btn_dash)

        row3.addWidget(create_dropdown_btn("📐 Margin ▼", load_templates("margin.json", fb_margin)))

        row3.addWidget(create_dropdown_btn("➖ Divider ▼", load_templates("divider.json", fb_divider)))
        
        row3.addStretch(1)
        
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addLayout(row3)

    def insert_quick_component(self, html):
        if not self.soup: return
        self.save_state_for_undo()
        sn = self.parse_html(html)

        styles = sn.find_all('style')
        els = [e for e in (sn.body or sn).children if isinstance(e, Tag)]

        for s in styles:
            if s not in els:
                els.insert(0, s)

        if not els: return
        
        t = self.current_node
        body = self.soup.find('body')
        if not body: return

        def get_active_page():
            for child in body.children:
                if isinstance(child, Tag) and child.name in ['div', 'section', 'main', 'article']:
                    cls_str = " ".join(child.get('class', [])).lower()
                    if 'header' in cls_str or 'footer' in cls_str or 'modal' in cls_str: continue
                    
                    style_str = str(child.get('style', '')).replace(' ', '').lower()
                    if 'display:none' not in style_str and 'hidden' not in cls_str:
                        return child
            return body

        def is_layout_container(tag):
            if not isinstance(tag, Tag): return False
            if tag.name in ['main', 'section', 'article']: return True
            cls_str = " ".join(tag.get('class', [])).lower()
            style_str = str(tag.get('style', '')).replace(' ', '').lower()
            if 'display:flex' in style_str or 'display:grid' in style_str: return True
            if any(k in cls_str for k in ['wrap', 'row', 'col', 'container', 'grid', 'page', 'sidebar', 'main-content']): return True
            return False
        target = t
        if not target or target.name in ['html', 'head', 'body']:
            target = get_active_page()

        last = None
        for e in els:
            if e.name in ['header', 'footer']:
                container_to_append = body # Default

                if target and target.name not in ['body', 'html']:

                    is_sidebar = 'sidebar' in target.get('class', [])
                    is_main = 'main-content' in target.get('class', [])
                    
                    parent_sidebar = target.find_parent(class_='sidebar')
                    parent_main = target.find_parent(class_='main-content')
                    
                    if is_sidebar or parent_sidebar:
                        container_to_append = target if is_sidebar else parent_sidebar
                    elif is_main or parent_main:
                        container_to_append = target if is_main else parent_main
                    elif is_layout_container(target):
                        container_to_append = target
                    else:
                        container_to_append = target.parent if target.parent else body
                else:
                    main_content = self.soup.find(class_='main-content')
                    if main_content: container_to_append = main_content

                if e.name == 'header':
                    container_to_append.insert(0, e)
                else:
                    container_to_append.append(e)
                    
                if e.name != 'style': last = e
                continue

            if target.name == 'body':
                target.append(e)
            else:
                void_tags = ['img', 'input', 'hr', 'br', 'meta', 'link', 'style']
                text_tags = ['p', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'label', 'button', 'i', 'b', 'strong']
                
                if target.name in void_tags or target.name in text_tags:

                    target.insert_after(e)
                else:

                    is_new_element_big = is_layout_container(e) or e.name == 'table' or 'card' in " ".join(e.get('class', [])).lower()
                    is_target_layout = is_layout_container(target)
                    
                    if is_new_element_big and not is_target_layout:

                        if target.parent and target.parent.name != 'body':
                            target.insert_after(e)
                        else:
                            target.append(e) # Safely place inside the tag so it does not spill out into Body
                    else:

                        target.append(e)

            if e.name != 'style': last = e
            
        self.refresh_tree()
        self.update_preview()
        if last: self.select_tree_item_by_id(str(id(last)))

        if not t or t.name == 'body':
            self.statusBar().showMessage("➕ Main design area found and tag inserted successfully!", 5000)
        else:
            self.statusBar().showMessage(f"➕ Block inserted successfully into the correct context of the currently selected area!", 3000)

    def replace_image_via_js(self):
        p = self.get_relative_path("Select Image", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not p: return
        self.save_state_for_undo()
        js = f"(function(){{ var t = window.lastContextTarget || window.lastClickTarget; if(t && t.tagName==='IMG') {{ t.setAttribute('src', {json.dumps(p)}); return 1; }} return 0; }})();"

        self.web_view.page().runJavaScript(js, 0, lambda r: self.sync_from_preview() if r==1 else QMessageBox.warning(self, "Error", "Image tag not found."))

    def sync_from_preview(self, *args):
        if not self.soup: return

        self.web_view.page().runJavaScript("document.documentElement.outerHTML", 0, self.process_synced_html)

    def process_synced_html(self, html, auto_save=False, auto_save_as=False):
        if not html or html == "null": return
        try:
            ns = self.parse_html(str(html))

            for tag in ns.find_all(attrs={"contenteditable": True}):
                del tag['contenteditable']
                
            for s_id in ["mini-app-editor-script", "mini-app-editor-style"]:
                s = ns.find(id=s_id); 
                if s: s.decompose()
            
            b = ns.find('body')
            if b is not None and len(b.find_all(True)) == 0 and len(self.soup.find('body').find_all(True)) > 0: return
            
            self.save_state_for_undo()
            if self.current_file_path:
                bd = os.path.dirname(os.path.abspath(self.current_file_path))
                for t in ns.find_all(True):
                    if 'data-editor-id' in t.attrs: del t['data-editor-id']
                    if 'class' in t.attrs and 'editor-highlight' in t['class']:
                        t['class'].remove('editor-highlight')
                        if not t['class']: del t['class']
                    for a in ['src', 'href']:
                        if t.has_attr(a) and isinstance(t[a], str) and t[a].startswith("file:///"):
                            lp = QUrl(t[a]).toLocalFile()
                            if lp: t[a] = os.path.relpath(lp, bd).replace('\\', '/')
            self.soup = ns
            self.refresh_tree(); self.update_preview()
            self.statusBar().showMessage("🔄 Synced back from View!", 4000)

            if auto_save:
                self.execute_save(self.current_file_path)
            elif auto_save_as:
                self.execute_save_as()
                
        except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def clone_node(self, node, id_map=None):
        import random, copy
        if isinstance(node, NavigableString): return type(node)(str(node))
        if not isinstance(node, Tag): return None
        
        nt = copy.copy(node)
        if id_map is None: id_map = {}

        for t in [nt] + nt.find_all(True):
            if 'data-editor-id' in t.attrs: 
                del t.attrs['data-editor-id']
                
            old_id = t.get('id')
            if old_id:
                if isinstance(old_id, list): old_id = old_id[0] # Safety
                if old_id not in id_map:
                    clean_id = old_id.split("_copy")[0] if "_copy" in old_id else old_id
                    id_map[old_id] = f"{clean_id}_copy{random.randint(100,999)}"
                t['id'] = id_map[old_id]
                
        return nt

    def kbd_adjust_font(self, delta):
        js = f"""
        (function() {{
            var target = window.currentEditingEl; // Get the tag where the cursor was placed for typing
            
            if (!target) {{ // If not typing but only highlighting text
                var sel = window.getSelection();
                if (sel.rangeCount > 0 && sel.toString().trim() !== "") {{
                    var node = sel.anchorNode;
                    target = node.nodeType === 3 ? node.parentNode : node;
                }}
            }}
            
            if (!target) target = document.querySelector('.editor-highlight'); // Fallback: use the currently highlighted (blue) tag
            
            if (target) {{
                var ce = target.closest('[data-editor-id]');
                if (ce) {{
                    var currentSize = parseFloat(window.getComputedStyle(ce).fontSize) || 16;
                    var newSize = Math.max(8, currentSize + ({delta}));
                    ce.style.setProperty('font-size', newSize + 'px', 'important'); // Force the size onto the view smoothly
                    return ce.getAttribute('data-editor-id') + '|' + newSize;
                }}
            }}
            return null;
        }})();
        """
        self.web_view.page().runJavaScript(js, 0, self._apply_font_shortcut_silent)

    def _apply_font_shortcut_silent(self, res):
        if not res: return
        try:
            eid, new_size = res.split('|')
            if eid in self.node_map:
                item = self.node_map[eid]
                t = item.data(0, Qt.ItemDataRole.UserRole)
                
                # 1. Silently update the style into Python (Soup) (Bypass update_preview to avoid screen flicker)
                st = str(t.get('style', ''))
                import re
                if 'font-size' in st:
                    new_st = re.sub(r'font-size:\s*[\d.]+px', f'font-size: {new_size}px', st)
                else:
                    new_st = st.strip(';') + ("; " if st else "") + f"font-size: {new_size}px;"
                
                t['style'] = new_st.strip('; ')
                
                # 2. Automatically re-populate the CSS Config Form on the left if that tag is currently selected
                if self.current_node == t:
                    self.on_item_clicked(item, 0)
                    
                self.statusBar().showMessage(f"📏 Current block font size: {new_size}px", 2000)
        except Exception as e:
            pass

    def kbd_copy(self):
        if self.tree.hasFocus():
            item = self.tree.currentItem()
            if item and isinstance(item.data(0, Qt.ItemDataRole.UserRole), Tag):
                self.copy_element(item, item.data(0, Qt.ItemDataRole.UserRole))

    def kbd_cut(self):
        if self.tree.hasFocus():
            item = self.tree.currentItem()
            if item and isinstance(item.data(0, Qt.ItemDataRole.UserRole), Tag):
                self.cut_element(item, item.data(0, Qt.ItemDataRole.UserRole))

    def kbd_paste(self):
        if self.tree.hasFocus():
            item = self.tree.currentItem()
            if item and isinstance(item.data(0, Qt.ItemDataRole.UserRole), Tag):
                self.paste_element(item, item.data(0, Qt.ItemDataRole.UserRole), "sibling")

    def kbd_duplicate(self):
        if self.tree.hasFocus():
            item = self.tree.currentItem()
            if item and isinstance(item.data(0, Qt.ItemDataRole.UserRole), Tag):
                self.quick_duplicate(item, item.data(0, Qt.ItemDataRole.UserRole))

    def kbd_delete(self):
        if self.tree.hasFocus():
            item = self.tree.currentItem()
            if item:
                t = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(t, Tag) and t.name not in ['body', 'html']:
                    self.delete_html_element(item, t)

    def show_context_menu(self, pos, from_web=False):
        if from_web:
            item = self.tree.currentItem()
            global_pos = pos 
        else:
            item = self.tree.itemAt(pos)
            if not item: return
            self.tree.setCurrentItem(item)
            self.on_item_clicked(item, 0)
            global_pos = self.tree.viewport().mapToGlobal(pos)

        if not item: return
        t = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(t, Tag): return

        m = QMenu(self)
        m.setStyleSheet("QMenu { background:#252526; color:white; border:1px solid #3e3e42; padding:5px; font-size:13px; font-weight:bold;} QMenu::item:selected {background:#094771;} QMenu::item:disabled {color:#666;}")
        
        if t.name == 'img': 
            m.addAction("🖼️ Quick image swap...").triggered.connect(lambda: self.quick_replace_image(item, t))
            m.addAction("🔄 Image fit mode (Crop to fill / Show entire image)").triggered.connect(lambda: self.toggle_image_fit(item, t))
            m.addSeparator()
            
        if len([c for c in t.children if isinstance(c, Tag)]) > 1: m.addAction("🔄 Reverse order").triggered.connect(lambda: self.reverse_children(item, t)); m.addSeparator()

        if t.name not in ['body', 'html']:
            menu_add_img = m.addMenu("➕ Insert Image (OUTSIDE - Adjacent)...")
            menu_add_img.addAction("⬅️ Insert to the Left").triggered.connect(lambda: self.insert_new_image_relative(item, t, "left"))
            menu_add_img.addAction("➡️ Insert to the Right").triggered.connect(lambda: self.insert_new_image_relative(item, t, "right"))
            menu_add_img.addAction("⬆️ Insert Above").triggered.connect(lambda: self.insert_new_image_relative(item, t, "above"))
            menu_add_img.addAction("⬇️ Insert Below").triggered.connect(lambda: self.insert_new_image_relative(item, t, "below"))
            
            menu_add_img_in = m.addMenu("📥 Add Image (INSIDE this tag)...")
            menu_add_img_in.addAction("⬅️ On the Left (Text wraps around)").triggered.connect(lambda: self.insert_new_image_inside(item, t, "left"))
            menu_add_img_in.addAction("➡️ On the Right (Text wraps around)").triggered.connect(lambda: self.insert_new_image_inside(item, t, "right"))
            menu_add_img_in.addAction("⬆️ On Top (Centered)").triggered.connect(lambda: self.insert_new_image_inside(item, t, "top"))
            menu_add_img_in.addAction("⬇️ On the Bottom (Centered)").triggered.connect(lambda: self.insert_new_image_inside(item, t, "bottom"))
            m.addSeparator()

        m.addAction("🛸 Draw Free Floating Image (Draggable)...").triggered.connect(lambda: self.insert_floating_image(item, t))

        st_t = str(t.get('style', '')).replace(' ', '')
        if 'position:absolute' in st_t or 'free-floating-element' in t.get('class', []):
            m_pin = m.addMenu("📌 Anchor / Pin Floating Image (Prevents flying off on zoom)...")
            m_pin.addAction("↖️ Anchor Top-Left Corner").triggered.connect(lambda: self.pin_floating_image(item, t, "top-left"))
            m_pin.addAction("↗️ Anchor Top-Right Corner").triggered.connect(lambda: self.pin_floating_image(item, t, "top-right"))
            m_pin.addAction("↙️ Anchor Bottom-Left Corner").triggered.connect(lambda: self.pin_floating_image(item, t, "bottom-left"))
            m_pin.addAction("↘️ Anchor Bottom-Right Corner").triggered.connect(lambda: self.pin_floating_image(item, t, "bottom-right"))
            m_pin.addAction("🎯 Anchor Center").triggered.connect(lambda: self.pin_floating_image(item, t, "center"))
            m_pin.addSeparator()
            m_pin.addAction("🔒 Lock Dragging (Fix current coordinates)").triggered.connect(lambda: self.lock_floating_image(item, t))
            
        m.addSeparator()

        m.addAction("🎨 Change Block Background Color...").triggered.connect(lambda: self.quick_change_bg_color(item, t))
        m.addAction("✨ Add Hover Effect...").triggered.connect(lambda: self.add_hover_effect(item, t))
        m.addAction("🔲 Toggle Border On/Off...").triggered.connect(lambda: self.toggle_border(item, t))

        m_text = m.addMenu("📝 Text Processing (Format & Edit)...")
        
        m_text.addAction("✂️ Cut Text (Cut)").triggered.connect(lambda: self.web_view.page().triggerAction(QWebEnginePage.WebAction.Cut))
        m_text.addAction("📋 Copy Text (Copy)").triggered.connect(lambda: self.web_view.page().triggerAction(QWebEnginePage.WebAction.Copy))
        m_text.addAction("📌 Paste Text (Paste)").triggered.connect(lambda: self.web_view.page().triggerAction(QWebEnginePage.WebAction.Paste))
        m_text.addSeparator()
        
        m_text.addAction("𝐁 Bold selected text (Ctrl+B)").triggered.connect(lambda: self.exec_text_cmd('bold'))
        m_text.addAction("𝐼 Italicize selected text (Ctrl+I)").triggered.connect(lambda: self.exec_text_cmd('italic'))
        m_text.addAction("̲U Underline selected text (Ctrl+U)").triggered.connect(lambda: self.exec_text_cmd('underline'))
        m_text.addAction("🎨 Color the highlighted text...").triggered.connect(self.change_selected_text_color)
        m_text.addSeparator()
        m_text.addAction("➕ Increase font size (Whole block +2px)").triggered.connect(lambda: self.change_font_size(t, 2))
        m_text.addAction("➖ Decrease font size (Whole block -2px)").triggered.connect(lambda: self.change_font_size(t, -2))
        m_text.addSeparator()
        m_text.addAction("⬅️ Align Left").triggered.connect(lambda: self.change_text_align(t, 'left'))
        m_text.addAction("↔️ Align Center").triggered.connect(lambda: self.change_text_align(t, 'center'))
        m_text.addAction("➡️ Align Right").triggered.connect(lambda: self.change_text_align(t, 'right'))

        if t.name not in ['body', 'html', 'img', 'input', 'br', 'hr']:
            m_add_text = m.addMenu("➕ Insert Text Box/Heading...")
            m_add_text.addAction("🔲 Draw Free Text Box (Floating & Resizable)").triggered.connect(lambda: self.insert_floating_textbox(t))
            m_add_text.addAction("🏷️ Large Heading (H1)").triggered.connect(lambda: self.insert_quick_html(t, '<h1 style="color:#007acc; margin-bottom:10px;">New Title</h1>'))
            m_add_text.addAction("💬 Text Paragraph (P)").triggered.connect(lambda: self.insert_quick_html(t, '<p style="line-height:1.6; opacity:0.8;">Enter your text content here...</p>'))
            
            # --- INSERT MULTI-DIRECTIONAL TABLE ---
            m_add_tbl = m.addMenu("📊 Insert Table (multi-directional)...")
            m_add_tbl.addAction("⬅️ On the Left (Split frame in half)").triggered.connect(lambda: self.insert_component_relative(item, t, "left", "table"))
            m_add_tbl.addAction("➡️ On the Right (Split frame in half)").triggered.connect(lambda: self.insert_component_relative(item, t, "right", "table"))
            m_add_tbl.addAction("⬆️ On Top (Push this tag down)").triggered.connect(lambda: self.insert_component_relative(item, t, "above", "table"))
            m_add_tbl.addAction("⬇️ On the Bottom (Push this tag up)").triggered.connect(lambda: self.insert_component_relative(item, t, "below", "table"))
            
        m.addSeparator()

        is_pagination = False
        pag_container = None

        if 'pagination' in t.get('class', []):
            is_pagination = True; pag_container = t
        elif t.parent and 'pagination' in t.parent.get('class', []):
            is_pagination = True; pag_container = t.parent
        elif 'nut-phan-trang' in t.get('class', []) and t.parent and 'pagination' in t.parent.get('class', []):
            is_pagination = True; pag_container = t.parent

        if is_pagination and pag_container:
            m.addAction("📄 ADD ANOTHER PAGE (Create new number + Blank frame)").triggered.connect(lambda: self.add_pagination_page(pag_container))
            m.addSeparator()

        m_add_layer = m.addMenu("📦 Add Layer / Category...")
        m_add_layer.addAction("📌 Add Blank Layer as SIBLING").triggered.connect(lambda: self.add_blank_layer(item, t, "sibling"))
        m_add_layer.addAction("📥 Add Blank Layer INSIDE (Child)").triggered.connect(lambda: self.add_blank_layer(item, t, "inside"))
        m_add_layer.addSeparator()
        m_add_layer.addAction("↳ Add Sub-item (Sub-menu Folder) to this Menu").triggered.connect(lambda: self.add_sub_item(item, t))
        m_add_layer.addAction("➖ Add Sibling Category").triggered.connect(lambda: self.add_sibling_category(item, t))
        m_add_layer.addAction("🔽 Create Hidden Content Block (Opens when this item is clicked)").triggered.connect(lambda: self.create_collapsible_content(item, t))
        m_add_layer.addAction("🔗 Open New Blank Page & Attach Link to this Button").triggered.connect(lambda: self.create_linked_page(item, t))
        
        m_add_layer.addSeparator()

        m_add_layer.addAction("📄 Create Blank Page (Attach as content for this Category)").triggered.connect(lambda: self.add_blank_page_to_menu(item, t))
        m_add_layer.addAction("🔢 Insert Inner Pagination (INSIDE this block)").triggered.connect(lambda: self.insert_inner_pagination(item, t))
        
        m_add_layer.addSeparator()

        m_add_layer.addAction("🧲 Attach SAFE Link/File Download (For dynamic Buttons)").triggered.connect(lambda: self.attach_safe_link(item, t))
        
        m.addSeparator()

        is_locked = t.get('data-locked') == 'true'
        if is_locked:
            m.addAction("🔓 UNLOCK Structure (Currently Locked)").triggered.connect(lambda: self.toggle_lock(item, t))
        else:
            m.addAction("🔒 LOCK Structure (Protect against CSS breakage)").triggered.connect(lambda: self.toggle_lock(item, t))
        m.addSeparator()

        m.addAction("📏 DRAG & DROP TOOLS:").setEnabled(False)
        a_vert = m.addAction("   ↕️ Drag Vertically (For Standalone Tags)")
        a_horz = m.addAction("   ↔️ Drag Horizontally (For Stacked Tags)")
        a_diag = m.addAction("   ⤡ Drag Corner (Images/Video only)")

        is_img = t.name in ['img', 'video', 'iframe']
        is_flex_child = False
        
        if t.parent:
            p_style = str(t.parent.get('style', '')).replace(' ', '').lower()
            p_class = str(t.parent.get('class', '')).lower()
            if 'flex' in p_style or 'grid' in p_style or 'row' in p_class or 'wrap' in p_class:
                is_flex_child = True

        if is_img:
            a_vert.setEnabled(False); a_horz.setEnabled(False)
            a_diag.triggered.connect(lambda: self.enable_resize_mode(t, "both"))
        else:
            a_diag.setEnabled(False)
            a_vert.triggered.connect(lambda: self.enable_resize_mode(t, "vertical"))
            if is_flex_child:
                a_horz.triggered.connect(lambda: self.enable_resize_mode(t, "horizontal"))
            else:
                a_horz.setEnabled(False) 

        m.addSeparator()
        m.addAction("⚙️ Enter manual size parameters...").triggered.connect(lambda: self.prepare_quick_resize(item, t))

        m.addAction("🛠️ Edit raw HTML code directly (Raw Code)...").triggered.connect(lambda: self.edit_raw_html(item, t))
        
        m.addSeparator()

        if t.name not in ['body', 'html']:
            m.addAction("👯 Duplicate (Duplicate)").triggered.connect(lambda: self.quick_duplicate(item, t))
            m.addAction("✂️ Cut HTML Tag (Cut)").triggered.connect(lambda: self.cut_element(item, t))
        m.addAction("📋 Copy HTML Tag (Smart Macro)").triggered.connect(lambda: self.copy_element(item, t))
        
        p_in = m.addAction("📌 Paste INSIDE"); p_in.triggered.connect(lambda: self.paste_element(item, t, "inside"))
        p_sib = m.addAction("📌 Paste as SIBLING"); p_sib.triggered.connect(lambda: self.paste_element(item, t, "sibling"))
        if t.name in ['body', 'html']: p_sib.setEnabled(False)
        if not self.clipboard_node: p_in.setEnabled(False); p_sib.setEnabled(False)

        m.addSeparator()
        if t.name not in ['body', 'html']: m.addAction("🗑️ DELETE").triggered.connect(lambda: self.delete_html_element(item, t))
        
        m.addSeparator()
        m.addAction("🔄 Sync content").triggered.connect(self.sync_from_preview)
        
        m.exec(global_pos)

    def enable_resize_mode(self, t, mode):
        eid = t.get('data-editor-id')
        if not eid: return
        
        is_img = t.name in ['img', 'video', 'iframe']

        js = f"""
        (function(){{
            var el = document.querySelector('[data-editor-id="{eid}"]');
            if(!el) return;

            if ({'true' if is_img else 'false'}) {{
                /* --- FIX FOR IMAGE CORNER-DRAG DOWN TO THE MILLIMETER --- */
                /* Since the default CSS resize does not work on IMG, we manually build a "Drag Handle" orange dot attached to the image */
                var oldH = document.getElementById('magic-img-resizer');
                if(oldH) oldH.remove();

                var hnd = document.createElement('div');
                hnd.id = 'magic-img-resizer';
                hnd.innerHTML = '⤡';
                hnd.style.cssText = 'position:absolute; width:28px; height:28px; background:#e67e22; color:#fff; text-align:center; line-height:28px; cursor:nwse-resize; z-index:2147483647; border-radius:50%; font-size:15px; box-shadow:0 2px 6px rgba(0,0,0,0.5); font-weight:bold;';
                document.body.appendChild(hnd);

                // Function to update the handle's position based on the image's real coordinates
                function updateHndPos() {{
                    var rect = el.getBoundingClientRect();
                    hnd.style.left = (rect.right - 14 + window.scrollX) + 'px';
                    hnd.style.top = (rect.bottom - 14 + window.scrollY) + 'px';
                }}
                updateHndPos();

                // Remove the barrier left over from the old configuration
                el.style.setProperty('max-width', 'none', 'important');
                el.style.setProperty('min-width', '10px', 'important');

                var isDragging = false;
                var startX, startY, startW, startH;

                hnd.addEventListener('mousedown', function(e) {{
                    isDragging = true;
                    startX = e.clientX; startY = e.clientY;
                    startW = el.offsetWidth; startH = el.offsetHeight;
                    e.preventDefault();
                    e.stopPropagation();
                }});

                function onMove(e) {{
                    if(!isDragging) return;
                    el.style.width = Math.max(20, startW + (e.clientX - startX)) + 'px';
                    el.style.height = Math.max(20, startH + (e.clientY - startY)) + 'px';
                    updateHndPos();
                }}

                function onUp(e) {{
                    if(isDragging) {{
                        isDragging = false;
                        hnd.remove();
                        window.removeEventListener('mousemove', onMove);
                        window.removeEventListener('mouseup', onUp);
                    }}
                }}

                window.addEventListener('mousemove', onMove);
                window.addEventListener('mouseup', onUp);
                
            }} else {{
                /* --- FIX FOR HORIZONTAL DRAG ON STACKED TAGS (FLEXBOX) --- */
                var compStyle = window.getComputedStyle(el);
                if(compStyle.flexGrow !== "0" && compStyle.display !== "none") {{
                    el.style.setProperty('flex', '0 0 auto', 'important');
                }}

                el.style.setProperty('resize', '{mode}', 'important');
                el.style.setProperty('overflow', 'auto', 'important');
            }}
            
            el.scrollIntoView({{behavior:'smooth', block:'center'}});
        }})();
        """
        self.web_view.page().runJavaScript(js)
        
        msg = "✅ The ⤡ orange drag handle has appeared at the image corner!" if is_img else "✅ The resize arrow has appeared at the bottom-right corner!"
        self.statusBar().showMessage(msg, 7000)

    def prepare_quick_resize(self, item, t):
        eid = t.get('data-editor-id')
        if not eid:
            self.show_resize_dialog(item, t, "")
            return
        
        js = f"""
        (function() {{
            var el = document.querySelector('[data-editor-id="{eid}"]');
            if(!el) return '';
            return el.offsetWidth + '|' + el.offsetHeight;
        }})();
        """
        self.web_view.page().runJavaScript(js, 0, lambda res: self.show_resize_dialog(item, t, res))

    def show_resize_dialog(self, item, t, real_info):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout, QComboBox, QCheckBox
        
        real_w = "Auto"; real_h = "Auto"
        if real_info and '|' in str(real_info):
            parts = str(real_info).split('|')
            if len(parts) >= 2:
                real_w = f"{parts[0]}px" if parts[0] != '0' else "Auto"
                real_h = f"{parts[1]}px" if parts[1] != '0' else "Auto"

        st = t.get('style', '')
        if isinstance(st, list): st = " ".join(st)
        
        style_dict = {}
        if st:
            for rule in st.split(';'):
                if ':' in rule:
                    k, v = rule.split(':', 1)
                    style_dict[k.strip().lower()] = v.strip()

        dialog = QDialog(self)
        dialog.setWindowTitle(f"📏 Customize Size: <{t.name}>")
        dialog.setStyleSheet("""
            QDialog { background-color: #252526; font-family: 'Segoe UI'; font-size: 13px; font-weight: bold; }
            QLabel { color: #ce9178; }
            QLineEdit, QComboBox { background-color: #1e1e1e; border: 1px solid #3e3e42; padding: 8px; color: #4fc1ff; border-radius: 4px; font-size: 14px;}
            QPushButton { background-color: #0e639c; color: white; padding: 10px; border-radius: 4px; border: none; font-size: 14px;}
            QPushButton:hover { background-color: #1177bb; }
            QCheckBox { color: #28a745; font-size: 13px; margin: 5px 0;}
        """)
        layout = QVBoxLayout(dialog)
        
        info_lbl = QLabel(f"💡 <b>Actual display size: {real_w} x {real_h}</b><br><i style='color:#888;font-size:12px;'>(Tip for large tags: it's best to leave Height as 'auto' so it hugs the content and text isn't clipped)</i>")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)
        
        form = QFormLayout()
        form.setContentsMargins(0, 10, 0, 10)
        
        inp_w = QLineEdit(style_dict.get('width', '')); inp_w.setPlaceholderText(f"E.g.: {real_w}, 100%, or auto")
        inp_h = QLineEdit(style_dict.get('height', '')); inp_h.setPlaceholderText("VD: auto")

        inp_ov = QComboBox()
        inp_ov.addItems(["(Default) Free", "Auto-generate scrollbar when long (auto)", "Hide overflowing content (hidden)"])
        old_ov = style_dict.get('overflow', '')
        if old_ov == 'auto': inp_ov.setCurrentIndex(1)
        elif old_ov == 'hidden': inp_ov.setCurrentIndex(2)

        inp_flex = QComboBox()
        inp_flex.addItems([
            "(Default per original code)", 
            "Stack elements vertically (Column - Prevents text overlap)", 
            "Arrange elements horizontally (Row)",
            "Center all content (Center)"
        ])
        old_display = style_dict.get('display', '')
        old_dir = style_dict.get('flex-direction', '')
        if old_display == 'flex' and old_dir == 'column': inp_flex.setCurrentIndex(1)
        elif old_display == 'flex' and old_dir == 'row': inp_flex.setCurrentIndex(2)
        elif old_display == 'flex': inp_flex.setCurrentIndex(3)

        form.addRow("Width:", inp_w)
        form.addRow("Cao (Height):", inp_h)
        form.addRow("Handle long content:", inp_ov)
        form.addRow("Arrange child elements:", inp_flex)
        
        layout.addLayout(form)
        
        btn_apply = QPushButton("✔️ Apply Settings")
        btn_apply.clicked.connect(dialog.accept)
        layout.addWidget(btn_apply)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.save_state_for_undo()
            
            def upd(key, val):
                if val: style_dict[key] = val
                elif key in style_dict: del style_dict[key]
            
            upd('width', inp_w.text().strip())
            upd('height', inp_h.text().strip())

            ov_val = ""
            if inp_ov.currentIndex() == 1: ov_val = "auto"
            elif inp_ov.currentIndex() == 2: ov_val = "hidden"
            upd('overflow', ov_val)

            flex_idx = inp_flex.currentIndex()
            if flex_idx == 1:
                style_dict['display'] = 'flex'
                style_dict['flex-direction'] = 'column'
                style_dict['gap'] = '10px' # Create even spacing between child elements, absolutely prevent overlap
            elif flex_idx == 2:
                style_dict['display'] = 'flex'
                style_dict['flex-direction'] = 'row'
                style_dict['gap'] = '10px'
            elif flex_idx == 3:
                style_dict['display'] = 'flex'
                style_dict['align-items'] = 'center'
                style_dict['justify-content'] = 'center'
            elif flex_idx == 0 and 'display' in style_dict and style_dict.get('display') == 'flex':
                del style_dict['display']
                if 'flex-direction' in style_dict: del style_dict['flex-direction']
                if 'gap' in style_dict: del style_dict['gap']

            new_style = "; ".join([f"{k}: {v}" for k, v in style_dict.items()])
            if new_style: t['style'] = new_style
            else:
                if 'style' in t.attrs: del t['style']
            
            self.on_item_clicked(item, 0)
            self.apply_changes()
            self.statusBar().showMessage(f"📐 Structure of tag <{t.name}> adjusted!", 3000)
    
    def toggle_image_fit(self, item, t):
        self.save_state_for_undo()
        st = str(t.get('style', ''))
        if 'object-fit: cover' in st or 'object-fit:cover' in st:
            new_st = st.replace('object-fit: cover', 'object-fit: contain').replace('object-fit:cover', 'object-fit:contain')
            msg = "Switched to: 🖼️ SHOW FULL IMAGE (Not cropped)"
        else:
            if 'object-fit' in st:
                new_st = st.replace('object-fit: contain', 'object-fit: cover').replace('object-fit:contain', 'object-fit:cover')
            else:
                new_st = st + ("; object-fit: cover;" if st else "object-fit: cover;")
            msg = "Switched to: ✂️ FILL & CROP TO FIT (Cover)"
        
        t['style'] = new_st
        self.on_item_clicked(item, 0)
        self.apply_changes()
        self.statusBar().showMessage(msg, 5000)
   
    def quick_change_bg_color(self, item, t):
        c = QColorDialog.getColor(QColor(), self, "Select Card Background Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid():
            self.save_state_for_undo()
            rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()/255.0:g})"
            st = t.get('style', '')
            if isinstance(st, list): st = " ".join(st)
            
            style_dict = {}
            if st:
                for rule in st.split(';'):
                    if ':' in rule:
                        k, v = rule.split(':', 1)
                        style_dict[k.strip().lower()] = v.strip()
            
            style_dict['background-color'] = rgba
            t['style'] = "; ".join([f"{k}: {v}" for k, v in style_dict.items()])
            
            self.on_item_clicked(item, 0) 
            self.apply_changes()
            self.statusBar().showMessage(f"🎨 Background of tag <{t.name}> changed!", 3000)

    def convert_to_link(self):
        if not self.current_node: return
        self.save_state_for_undo()
        t = self.current_node
        
        parent_node = t.parent

        if t.name == 'button':
            t.name = 'a'
            t['href'] = '#'
            msg = "🪄 Button (button) magically transformed into a Link (a)!"
            target_node = t
            update_node = t

        else:
            new_a = self.soup.new_tag('a', href='#')
            new_a['style'] = "text-decoration: none; color: inherit; display: inline-block;"
            t.wrap(new_a)
            msg = f"🪄 Protective Link wrapped around tag <{t.name}>!"
            target_node = new_a
            update_node = parent_node 
            
        self.refresh_tree()

        if update_node and update_node.name not in ['body', 'html']:
            eid = update_node.get('data-editor-id')
            if eid:
                import base64
                b64_html = base64.b64encode(str(update_node).encode('utf-8')).decode('utf-8')
                js = f"""
                (function(){{
                    var el = document.querySelector('[data-editor-id="{eid}"]');
                    if(el) {{
                        var temp = document.createElement('div');
                        temp.innerHTML = decodeURIComponent(escape(window.atob('{b64_html}')));
                        var newEl = temp.firstElementChild;
                        if(newEl) {{ el.replaceWith(newEl); }}
                    }}
                }})();
                """
                self.web_view.page().runJavaScript(js)
            else:
                self.update_preview()
        else:
            self.update_preview()
            
        new_id = str(id(target_node))
        if new_id in self.node_map:
            self.select_tree_item_by_id(new_id)
            
        self.statusBar().showMessage(msg, 5000)

    def insert_floating_image(self, item, t):
        self.save_state_for_undo()

        if t.name not in ['body', 'html']:
            parent_st = str(t.get('style', ''))
            if 'position' not in parent_st:
                t['style'] = parent_st.strip(';') + ("; " if parent_st else "") + "position: relative;"
        
        new_img = self.soup.new_tag('img', src='https://via.placeholder.com/150x100?text=Keo+Tha+Toi')

        new_img['class'] = 'free-floating-element'

        new_img['style'] = "position: absolute; z-index: 9999; top: 10px; left: 10px; width: 150px; height: auto; object-fit: contain; cursor: move; border: 2px dashed #ff9800; border-radius: 8px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); background: rgba(255,255,255,0.8);"
        
        t.append(new_img)
        
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(new_img))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage("🛸 Floating Image created! Use the mouse to DRAG it to the position you want, then Right-click -> Select 'Quick image swap'.", 7000)

    def quick_replace_image(self, item, t):
        p, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if p:
            self.save_state_for_undo()
            old_src = str(t.get('src', '')).strip()

            try:
                base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
                target_path = os.path.relpath(p, base_dir).replace('\\', '/')
            except (ValueError, TypeError):
                target_path = "file:///" + p.replace('\\', '/')
                
            t['src'] = target_path
            self.inp_src.setText(target_path)
            
            for attr in list(t.attrs.keys()):
                if attr == 'src': continue
                val = str(t[attr])
                if old_src and old_src in val:
                    t[attr] = val.replace(old_src, target_path)
                elif attr == 'onerror' and "this.src=" in val.replace(" ", ""):
                    t[attr] = f"this.src='{target_path}'"
            
            st = str(t.get('style', '')).strip()
            import re

            if 'free-floating-element' in t.get('class', []):
                st = re.sub(r'border:\s*[^;]+;?', '', st)
                st = re.sub(r'background:\s*[^;]+;?', '', st)
                st = re.sub(r'box-shadow:\s*[^;]+;?', '', st)

            st = re.sub(r'height:\s*auto;?', '', st) 
            
            if 'object-fit' not in st: st = st.strip(';') + ("; " if st else "") + "object-fit: contain;"
            if 'max-width' not in st: st = st.strip(';') + ("; " if st else "") + "max-width: 100%;"
            t['style'] = st.strip('; ')
                    
            item.setText(0, self.format_node_title(t))
            
            # --- ANTI SPA-JUMP TECHNOLOGY ---
            eid = t.get('data-editor-id')
            if eid and t.name not in ['body', 'html']:
                import base64
                b64_html = base64.b64encode(str(t).encode('utf-8')).decode('utf-8')
                js = f"""
                (function(){{
                    var el = document.querySelector('[data-editor-id="{eid}"]');
                    if(el) {{
                        var temp = document.createElement('div');
                        temp.innerHTML = decodeURIComponent(escape(window.atob('{b64_html}')));
                        var newEl = temp.firstElementChild;
                        if(newEl) {{
                            el.replaceWith(newEl);
                            setTimeout(() => newEl.classList.add('editor-highlight'), 50);
                        }}
                    }}
                }})();
                """
                self.web_view.page().runJavaScript(js)
            else:
                self.update_preview()
                
            self.statusBar().showMessage("🖼️ Image changed successfully!", 4000)

    def pin_floating_image(self, item, t, position):
        self.save_state_for_undo()
        eid = t.get('data-editor-id')
        if not eid: return

        js = f"""
        (function(){{
            var img = document.querySelector('[data-editor-id="{eid}"]');
            if(!img) return "0|";
            
            var imgRect = img.getBoundingClientRect();
            var pos = "{position}";
            
            // 1. FIND THE EXACT HOST ELEMENT: Cast an X-ray from the EXACT CENTER of the image so it never drifts off target
            var cx = imgRect.left + imgRect.width / 2;
            var cy = imgRect.top + imgRect.height / 2;
            
            img.style.display = 'none';
            var underEls = document.elementsFromPoint(cx, cy);
            img.style.display = 'block';
            
            var underEl = null;
            // Skip tags that only contain text, prioritize snapping to Block tags (Div, Nav, Section, Header...)
            var avoidTags = ['BODY', 'HTML', 'MAIN', 'P', 'SPAN', 'B', 'I', 'A', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'IMG', 'BUTTON', 'LI', 'UL', 'OL'];
            
            for(var i=0; i<underEls.length; i++) {{
                var el = underEls[i];
                if(el.id === 'mini-app-editor-style' || el.id === 'mini-app-editor-script') continue;
                if(!avoidTags.includes(el.tagName)) {{
                    underEl = el;
                    break;
                }}
            }}
            
            // Step back out to find a wrapper tag in case it accidentally hit a text cluster
            if(!underEl && underEls.length > 0) {{ 
                var directHit = underEls[0];
                while(directHit && directHit.parentElement && avoidTags.includes(directHit.tagName)) {{
                    directHit = directHit.parentElement;
                }}
                underEl = directHit || document.body;
            }}
            if(!underEl) underEl = document.body;
            
            // 2. INJECT ANESTHETIC (POSITION: RELATIVE) INTO THE HOST TO SERVE AS THE ANCHOR POINT
            var compStyle = window.getComputedStyle(underEl);
            if (compStyle.position === 'static') {{
                underEl.style.setProperty('position', 'relative', 'important');
            }}
            
            // 3. RELOCATE (MOVE THE IMAGE'S DOM NODE INTO THE NEWLY FOUND HOST)
            if(img.parentElement !== underEl) {{
                underEl.appendChild(img);
            }}
            
            // 4. CALCULATE SPACING COMPENSATION (INCLUDING PROTECTIVE BORDER THICKNESS)
            var pRect = underEl.getBoundingClientRect();
            var bTop = parseFloat(compStyle.borderTopWidth) || 0;
            var bLeft = parseFloat(compStyle.borderLeftWidth) || 0;
            var bRight = parseFloat(compStyle.borderRightWidth) || 0;
            var bBottom = parseFloat(compStyle.borderBottomWidth) || 0;
            
            // Host's inner margin coordinates (Padding box)
            var pInnerTop = pRect.top + bTop;
            var pInnerLeft = pRect.left + bLeft;
            var pInnerRight = pRect.right - bRight;
            var pInnerBottom = pRect.bottom - bBottom;
            
            img.style.removeProperty('left');
            img.style.removeProperty('top');
            img.style.removeProperty('right');
            img.style.removeProperty('bottom');
            img.style.removeProperty('transform');
            img.style.removeProperty('margin');
            
            // Lock the exact pixel value, whether negative or positive
            if (pos === 'top-left') {{ 
                img.style.top = (imgRect.top - pInnerTop) + 'px'; 
                img.style.left = (imgRect.left - pInnerLeft) + 'px'; 
            }}
            else if (pos === 'top-right') {{ 
                img.style.top = (imgRect.top - pInnerTop) + 'px'; 
                img.style.right = (pInnerRight - imgRect.right) + 'px'; 
            }}
            else if (pos === 'bottom-left') {{ 
                img.style.bottom = (pInnerBottom - imgRect.bottom) + 'px'; 
                img.style.left = (imgRect.left - pInnerLeft) + 'px'; 
            }}
            else if (pos === 'bottom-right') {{ 
                img.style.bottom = (pInnerBottom - imgRect.bottom) + 'px'; 
                img.style.right = (pInnerRight - imgRect.right) + 'px'; 
            }}
            else if (pos === 'center') {{ 
                img.style.top = '50%'; 
                img.style.left = '50%'; 
                img.style.transform = 'translate(-50%, -50%)'; 
            }}
            
            // Flash a border to indicate
            var oldBoxShadow = img.style.boxShadow;
            img.style.boxShadow = '0 0 20px #00ff00, 0 0 40px #00ff00';
            setTimeout(() => {{ img.style.boxShadow = oldBoxShadow; }}, 800);
            
            var targetName = underEl.tagName.toLowerCase() + (underEl.className ? '.' + underEl.className.split(' ')[0] : '');
            return "1|" + targetName;
        }})();
        """
        
        self.web_view.page().runJavaScript(js, 0, lambda r: self._post_pin_floating_image(r, position, eid))

    def _post_pin_floating_image(self, res, position, eid):
        if isinstance(res, str) and res.startswith("1|"):
            target_name = res.split("|")[1]
            self.web_view.page().runJavaScript("document.documentElement.outerHTML", 0, lambda html: self._sync_and_reselect(html, eid, position, target_name))
        else:
            self.statusBar().showMessage("⚠️ Error: Image not found to anchor.", 3000)

    def _sync_and_reselect(self, html, eid, position, target_name):
        self.process_synced_html(html)
        if eid in self.node_map:
            self.select_tree_item_by_id(eid)

        if target_name == "body":
            self.statusBar().showMessage(f"⚠️ WARNING: The image is sticking out too far, so it is anchoring to the outermost screen edge. Try dragging it a bit further inward, then Anchor again!", 8000)
        else:
            self.statusBar().showMessage(f"🧲 MAGNET TECHNOLOGY: Image snapped into Block [{target_name}] & pixel-locked to the {position.upper()} corner!", 8000)

    def lock_floating_image(self, item, t):
        self.save_state_for_undo()

        cls = t.get('class', [])
        if isinstance(cls, str): cls = [cls]
        if 'free-floating-element' in cls:
            cls.remove('free-floating-element')
            t['class'] = cls
            if not t['class']: del t['class']

        st = str(t.get('style', '')).strip()
        import re
        st = re.sub(r'cursor:\s*move;?', '', st)
        t['style'] = st.replace('  ', ' ').strip('; ')
        
        self.on_item_clicked(item, 0)
        self.apply_changes()
        
        self.statusBar().showMessage("🔒 Current position locked! The floating Image's coordinates are now fully fixed.", 5000)

    def reverse_children(self, item, t):
        self.save_state_for_undo()
        cts = list(t.contents)
        cts.reverse() 
        t.clear()
        for c in cts: t.append(c)
        item.takeChildren()
        self.build_dom_tree(item, t, 99)

        eid = t.get('data-editor-id')
        if eid and t.name not in ['body', 'html']:
            import base64
            b64_html = base64.b64encode(str(t).encode('utf-8')).decode('utf-8')
            js = f"""
            (function(){{
                var el = document.querySelector('[data-editor-id="{eid}"]');
                if(el) {{
                    var temp = document.createElement('div');
                    temp.innerHTML = decodeURIComponent(escape(window.atob('{b64_html}')));
                    var newEl = temp.firstElementChild;
                    if(newEl) {{
                        el.replaceWith(newEl);
                        setTimeout(() => newEl.classList.add('editor-highlight'), 50);
                    }}
                }}
            }})();
            """
            self.web_view.page().runJavaScript(js)
        else:
            self.update_preview()
            
        self.statusBar().showMessage("🔄 Child element order reversed!", 3000)
       
    def quick_duplicate(self, item, t):
        self.save_state_for_undo()
        try:
            import random
            id_map = {}
            companions = []
            
            target_ids = []
            for tag in [t] + t.find_all(True):
                if tag.get('data-trang'): target_ids.append(tag.get('data-trang'))
                href = tag.get('href')
                if href and isinstance(href, str) and href.startswith('#') and len(href)>1:
                    target_ids.append(href[1:])
            
            for tid in set(target_ids):
                comp = self.soup.find(id=tid)
                if comp and comp != t and comp not in companions:
                    companions.append(comp)
                    
            own_ids = []
            for tag in [t] + t.find_all(True):
                if tag.get('id'): own_ids.append(tag.get('id'))
                
            all_tags = self.soup.find_all(True)
            for oid in set(own_ids):
                for el in all_tags:
                    if el == t or el in t.parents or el in t.descendants: continue
                    is_pointing = False
                    if el.get('data-trang') == oid: is_pointing = True
                    if el.get('href') == f"#{oid}": is_pointing = True
                    
                    if is_pointing:
                        target_to_clone = el
                        if el.parent and el.parent.name in ['li', 'div', 'p']:
                            real_children = [c for c in el.parent.children if isinstance(c, Tag) or (isinstance(c, NavigableString) and c.strip())]
                            if len(real_children) == 1: target_to_clone = el.parent
                        if target_to_clone not in companions:
                            companions.append(target_to_clone)

            cloned_nodes = []
            
            for comp in companions:
                n_comp = self.clone_node(comp, id_map)
                if n_comp:
                    comp.insert_after(n_comp)
                    cloned_nodes.append(n_comp)
                    
            nt = self.clone_node(t, id_map)
            if nt:
                t.insert_after(nt)
                cloned_nodes.append(nt)
                
            for c_node in cloned_nodes:
                if c_node.name in ['a', 'button', 'li'] or c_node.find(['a', 'button']):
                    text_nodes = list(c_node.find_all(string=True))
                    for s in text_nodes:
                        if s.strip() and "(Copy)" not in s and len(s.strip()) < 30:
                            if c_node.name in ['a', 'button', 'li'] or any(p.name in ['a', 'button', 'li'] for p in s.parents):
                                s.replace_with(str(s) + " (Copy)")
                                break
            
            for c_node in cloned_nodes:
                for tag in [c_node] + c_node.find_all(True):
                    for attr in ['href', 'data-trang', 'data-target', 'aria-controls']:
                        if tag.has_attr(attr):
                            val = tag[attr]
                            if isinstance(val, str):
                                if attr == 'href' and val.startswith('#'):
                                    clean_id = val[1:]
                                    if clean_id in id_map: tag[attr] = f"#{id_map[clean_id]}"
                                elif val in id_map:
                                    tag[attr] = id_map[val]
                            elif isinstance(val, list):
                                new_list = []
                                for v in val:
                                    if attr == 'href' and v.startswith('#'):
                                        clean_id = v[1:]
                                        new_list.append(f"#{id_map[clean_id]}" if clean_id in id_map else v)
                                    else:
                                        new_list.append(id_map[v] if v in id_map else v)
                                tag[attr] = new_list

            self.refresh_tree()
            self.update_preview()
            
            if len(companions) > 0:
                self.statusBar().showMessage(f"👯 Macro Successful: Duplicated the source Block + {len(companions)} linked satellite Blocks!", 5000)
            else:
                self.statusBar().showMessage("👯 Duplicated independently.", 5000)
                
        except Exception as e:
            self.statusBar().showMessage(f"⚠️ Macro Error: {str(e)}", 7000)

    def insert_new_image_relative(self, item, t, position):
        if not self.current_file_path:
            QMessageBox.warning(self, "Error", "Please open an HTML file.")
            return

        base_dir = os.path.dirname(os.path.abspath(self.current_file_path))

        p, _ = QFileDialog.getOpenFileName(self, "Select Free Image", "", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not p: return

        try:
            target_path = os.path.relpath(p, base_dir).replace('\\', '/')
        except ValueError:
            target_path = "file:///" + p.replace('\\', '/')
            
        self.save_state_for_undo()
        
        new_img = self.soup.new_tag('img', src=target_path)
        new_img['style'] = "max-width: 100%; height: auto; object-fit: contain;"

        if position in ["above", "below"]:
            new_img['style'] += " display: block; margin: 15px auto;"
            if position == "above": t.insert_before(new_img)
            else: t.insert_after(new_img)
            
        elif position in ["left", "right"]:
            main_wrapper = self.soup.new_tag('div')
            main_wrapper['class'] = "grid-wrap"
            main_wrapper['style'] = "display: grid; grid-template-columns: 1fr 1fr; gap: 15px; width: 100%; align-items: center;"

            t_wrapper = self.soup.new_tag('div')
            t_wrapper['class'] = "grid-item-text"
            t_wrapper['style'] = "min-width: 0; width: 100%;"

            img_wrapper = self.soup.new_tag('div')
            img_wrapper['class'] = "grid-item-img"
            img_wrapper['style'] = "min-width: 0; width: 100%; display: flex; justify-content: center;"
            img_wrapper.append(new_img)

            t.insert_before(main_wrapper)
            t_extracted = t.extract()
            t_wrapper.append(t_extracted)
            
            if position == "left":
                main_wrapper.append(img_wrapper)
                main_wrapper.append(t_wrapper)
            else:
                main_wrapper.append(t_wrapper)
                main_wrapper.append(img_wrapper)
                
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(new_img))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(f"✅ Image safely inserted (Allowed to select outside the working folder)!", 4000)

    def insert_new_image_inside(self, item, t, position):
        if not self.current_file_path:
            QMessageBox.warning(self, "Error", "Please open a file.")
            return

        base_dir = os.path.dirname(os.path.abspath(self.current_file_path))

        p, _ = QFileDialog.getOpenFileName(self, "Select Free Image", "", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not p: return

        try:
            target_path = os.path.relpath(p, base_dir).replace('\\', '/')
        except ValueError:
            target_path = "file:///" + p.replace('\\', '/')
            
        self.save_state_for_undo()
        
        new_img = self.soup.new_tag('img', src=target_path)

        base_style = "width: 33.33%; max-width: 100%; height: auto; object-fit: contain; flex-shrink: 0; min-width: 0; "
        
        if position == "left":
            new_img['style'] = base_style + "float: left; margin: 0 15px 15px 0;"
            t.insert(0, new_img) 
        elif position == "right":
            new_img['style'] = base_style + "float: right; margin: 0 0 15px 15px;"
            t.insert(0, new_img) 
        elif position == "top":
            new_img['style'] = base_style + "display: block; margin: 0 auto 15px auto;"
            t.insert(0, new_img) 
        elif position == "bottom":
            new_img['style'] = base_style + "display: block; margin: 15px auto 0 auto;"
            t.append(new_img) 

        if position in ["left", "right"]:
            st = str(t.get('style', '')).strip()
            if 'overflow' not in st: st = st.strip(';') + ("; " if st else "") + "overflow: hidden;"
            t['style'] = st.strip('; ')
                
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(new_img))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(f"✅ Free image inserted INSIDE the tag (Standard wrap-around Magazine style)!", 4000)

    def insert_component_relative(self, item, t, position, comp_type):
        self.save_state_for_undo()
        
        html_str = ''
        if comp_type == "table":

            html_str = '<div style="overflow-x:auto;padding:10px;width:100%;"><table style="width:100%;border-collapse:collapse;margin:15px 0;font-family:sans-serif;color:inherit;"><tr style="background:#007acc;color:white;text-align:left;"><th style="padding:12px 15px;">ID</th><th style="padding:12px 15px;">Full Name</th><th style="padding:12px 15px;">Status</th></tr><tr style="border-bottom: 1px solid rgba(150,150,150,0.3);"><td style="padding:12px 15px;">#01</td><td style="padding:12px 15px;">John Smith</td><td style="padding:12px 15px;"><span style="background:#28a745;color:white;padding:4px 8px;border-radius:12px;font-size:12px;">Active</span></td></tr></table></div>' 
            
        new_soup = self.parse_html(html_str)
        els = [e for e in (new_soup.body or new_soup).children if isinstance(e, Tag)]
        if not els: return
        new_el = els[0]

        if position in ["above", "below"]:
            if position == "above": t.insert_before(new_el)
            else: t.insert_after(new_el)

        elif position in ["left", "right"]:
            main_wrapper = self.soup.new_tag('div')
            main_wrapper['class'] = "grid-wrap"
            main_wrapper['style'] = "display: grid; grid-template-columns: 1fr 1fr; gap: 15px; width: 100%; align-items: start;"
            
            t_wrapper = self.soup.new_tag('div')
            t_wrapper['class'] = "grid-item-original"
            t_wrapper['style'] = "min-width: 0; width: 100%;"
            
            comp_wrapper = self.soup.new_tag('div')
            comp_wrapper['class'] = "grid-item-new-comp"
            comp_wrapper['style'] = "min-width: 0; width: 100%;"
            comp_wrapper.append(new_el)
            
            t.insert_before(main_wrapper)
            t_extracted = t.extract()
            t_wrapper.append(t_extracted)
            
            if position == "left":
                main_wrapper.append(comp_wrapper)
                main_wrapper.append(t_wrapper)
            else:
                main_wrapper.append(t_wrapper)
                main_wrapper.append(comp_wrapper)
                
        self.refresh_tree()
        self.update_preview()

        new_id = str(id(new_el))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(f"✅ Table inserted successfully at position ({position}), absolutely safe!", 4000)

    def add_blank_layer(self, item, t, mode):

        if mode == "inside" and hasattr(self, 'check_locked') and self.check_locked(t):
            QMessageBox.warning(self, "CSS Protection", "This block is currently 🔒 LOCKED.\nThe Tool refuses to nest a tag inside it to avoid breaking the interface!\n\nPlease choose the 'Sibling' insert mode instead.")
            return

        self.save_state_for_undo()
        blank_div = self.soup.new_tag('div')

        blank_div['class'] = "layer-wrapper"
        blank_div['style'] = "min-height: 100px; padding: 20px; background: rgba(0,0,0,0.03); border: 2px dashed #007acc; width: 100%; box-sizing: border-box; margin-bottom: 15px;"
        blank_div.string = "New content layer..."

        if mode == "inside":
            t.append(blank_div)
            msg = "📥 A Blank Layer has been nested INSIDE this object!"
        else:
            if t.name in ['body', 'html']:
                QMessageBox.warning(self, "Logic Error", "The Body tag is the top level, cannot insert as a sibling. Automatically switched to inserting inside (Child) instead!")
                t.append(blank_div)
                msg = "📥 A Blank Layer has been nested INSIDE the Body tag."
            else:
                t.insert_after(blank_div)
                msg = "📌 A Blank Layer has been placed as a SIBLING of this object!"

        self.refresh_tree()
        self.update_preview()

        new_id = str(id(blank_div))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(msg, 5000)

    def add_sub_item(self, item, t):
        from PySide6.QtWidgets import QMessageBox
        if hasattr(self, 'check_locked') and self.check_locked(t):
            QMessageBox.warning(self, "CSS Protection", "This object is currently 🔒 LOCKED.\nCannot nest a Sub-item inside it!")
            return

        if t.find_parent('nav') or 'pagination' in t.get('class', []) or t.find_parent(class_='pagination-wrapper'):
            QMessageBox.warning(self, "Structure Protection", "The 'Add Sub-item' (Dropdown) feature is only supported for vertical Sidebar Menus.\nCannot be applied to horizontal Navigation or Pagination, as it will completely break the Layout!")
            return

        self.save_state_for_undo()
        import random

        curr = t
        target_trigger = None
        target_folder = None

        while curr and curr.name not in ['body', 'html', 'main', 'aside']:
            classes = curr.get('class', [])
            if isinstance(classes, str): classes = [classes]

            if 'menu-con' in classes:
                target_folder = curr
                prev = curr.find_previous_sibling(True) # Get any tag immediately above it
                if prev: target_trigger = prev
                break

            if curr.name in ['a', 'button'] or curr.get('data-menu') or any('nut-' in c for c in classes):
                target_trigger = curr
                break

            if curr.name in ['div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'p', 'span']:
                # Skip large layout blocks to avoid false detection
                if not any(k in c for c in classes for k in ['menu-group', 'sidebar', 'vung-noi-dung', 'container']):
                    target_trigger = curr
                    break
                
            curr = curr.parent

        if not target_trigger and not target_folder:
            QMessageBox.warning(self, "Selection Error", "Please click on a category (a tag, div...) on the left to create a Sub-item!")
            return

        if target_trigger and not target_folder:
            menu_id = target_trigger.get('data-menu')
            if menu_id:
                target_folder = self.soup.find(id=menu_id)
            if not target_folder:

                nxt = target_trigger.find_next_sibling('div')
                if nxt and 'menu-con' in nxt.get('class', []):
                    target_folder = nxt

        is_first_time = False if target_folder else True
        
        safe_a_style = "display: flex; align-items: center; justify-content: space-between; padding: 10px 15px; margin-bottom: 5px; color: #a0aec0; text-decoration: none; border-radius: 8px; transition: 0.2s; font-size: 13.5px;"
        
        js_tab_switch = "var tId=this.getAttribute('data-trang'); document.querySelectorAll('.trang-noi-dung').forEach(function(el){el.classList.remove('trang-dang-hien-thi'); el.style.display='none';}); var target=document.getElementById(tId); if(target){target.classList.add('trang-dang-hien-thi'); target.style.display='block';} document.querySelectorAll('.nut-chuyen-trang').forEach(function(btn){btn.classList.remove('menu-dang-chon'); if(btn.getAttribute('data-trang')===tId) btn.classList.add('menu-dang-chon');});"

        parent_name = target_trigger.get_text(strip=True).replace('▼', '').strip() if target_trigger else "Category"

        if is_first_time:

            menu_id = f"menu-con-{random.randint(1000, 9999)}"
            
            target_folder = self.soup.new_tag('div', id=menu_id)
            target_folder['class'] = "menu-con mo-ra"
            target_folder['style'] = "display: block; margin-left: 15px; padding-left: 10px; border-left: 1px solid #2a3441; margin-bottom: 10px;"
            target_trigger.insert_after(target_folder)

            old_data_trang = target_trigger.get('data-trang')
            if 'data-trang' in target_trigger.attrs:
                del target_trigger['data-trang']

            classes = target_trigger.get('class', [])
            if isinstance(classes, str): classes = [classes]
            classes = [c for c in classes if c not in ['nut-chuyen-trang', 'menu-dang-chon']]
            if 'nut-mo-menu-con' not in classes: classes.append('nut-mo-menu-con')
            if 'xo-menu' not in classes: classes.append('xo-menu')
            target_trigger['class'] = classes
            target_trigger['data-menu'] = menu_id
            
            st = str(target_trigger.get('style', ''))
            if 'cursor: pointer' not in st and 'cursor:pointer' not in st:
                target_trigger['style'] = st.strip(';') + ("; " if st else "") + "cursor: pointer;"
            
            target_trigger['onclick'] = f"var m=document.getElementById('{menu_id}'); if(m.classList.contains('mo-ra')){{ m.classList.remove('mo-ra'); m.style.display='none'; this.classList.remove('xo-menu'); }} else {{ m.classList.add('mo-ra'); m.style.display='block'; this.classList.add('xo-menu'); }}"
            
            if not target_trigger.find('span', class_='mui-ten'):
                target_trigger.clear()
                span_text = self.soup.new_tag('span')
                span_text.string = parent_name
                target_trigger.append(span_text)
                
                icon = self.soup.new_tag('span')
                icon['class'] = 'mui-ten'
                icon['style'] = "font-size: 10px; transition: 0.2s;"
                icon.string = "▼"
                target_trigger.append(" ")
                target_trigger.append(icon)

            child_1 = self.soup.new_tag('a')
            child_1['class'] = "nut-chuyen-trang"
            child_1['style'] = safe_a_style
            if old_data_trang:
                child_1['data-trang'] = old_data_trang
            else:
                child_1['data-trang'] = f"trang-con-{random.randint(10000, 99999)}"
            child_1['onclick'] = js_tab_switch
            child_1.string = f"↳ a. {parent_name} (Original)"
            target_folder.append(child_1)
            
            new_page_id = f"trang-con-{random.randint(10000, 99999)}"
            child_2 = self.soup.new_tag('a')
            child_2['class'] = ["nut-chuyen-trang", "menu-dang-chon"]
            child_2['style'] = safe_a_style
            child_2['data-trang'] = new_page_id
            child_2['onclick'] = js_tab_switch
            child_2.string = "↳ b. New Sub-item"
            target_folder.append(child_2)
            
            msg = "📘 The Category has been turned into a Book Cover, inheriting the old content and creating an empty item b.!"

            child_count = len([c for c in target_folder.children if c.name == 'a'])
            char_prefix = chr(97 + child_count) if child_count < 26 else str(child_count + 1)
            new_page_id = f"trang-con-{random.randint(10000, 99999)}"
            
            new_child = self.soup.new_tag('a')
            new_child['class'] = ["nut-chuyen-trang", "menu-dang-chon"]
            new_child['style'] = safe_a_style
            new_child['data-trang'] = new_page_id
            new_child['onclick'] = js_tab_switch
            new_child.string = f"↳ {char_prefix}. New Sub-item"
            target_folder.append(new_child)

            folder_cls = target_folder.get('class', [])
            if isinstance(folder_cls, str): folder_cls = [folder_cls]
            if 'mo-ra' not in folder_cls:
                folder_cls.append('mo-ra')
            target_folder['class'] = folder_cls
            
            target_folder['style'] = "display: block; margin-left: 15px; padding-left: 10px; border-left: 1px solid #2a3441; margin-bottom: 10px;"
            msg = f"📥 Sub-item ({char_prefix}) added to the existing category!"


        for old_btn in self.soup.find_all(class_='menu-dang-chon'):
            if old_btn.get('data-trang') == new_page_id: continue 
            cls = old_btn.get('class', [])
            if isinstance(cls, str): cls = [cls]
            if 'menu-dang-chon' in cls:
                cls.remove('menu-dang-chon')
                old_btn['class'] = cls

        existing_pages = self.soup.find_all(class_='trang-noi-dung')
        for old_page in existing_pages:
            cls = old_page.get('class', [])
            if isinstance(cls, str): cls = [cls]
            if 'trang-dang-hien-thi' in cls:
                cls.remove('trang-dang-hien-thi')
                old_page['class'] = cls
            st = str(old_page.get('style', ''))
            if 'display: block' in st: old_page['style'] = st.replace('display: block', 'display: none')
            elif 'display' not in st: old_page['style'] = st.strip(';') + ("; " if st else "") + "display: none;"

        new_page = self.soup.new_tag('div', id=new_page_id)
        new_page['class'] = ["trang-noi-dung", "trang-dang-hien-thi"]
        new_page['style'] = "display: block;"
        
        title = self.soup.new_tag('h2')
        title['class'] = "tieu-de-muc"
        title.string = f"{parent_name} > Workspace"
        new_page.append(title)
        
        box = self.soup.new_tag('div')
        box['class'] = "khung-bai-viet"
        box['style'] = "border: 2px dashed #00d9ff; min-height: 300px; padding: 30px; margin-top: 20px;"
        
        desc = self.soup.new_tag('h3')
        desc['style'] = "color: #00d9ff; margin-bottom: 10px;"
        desc.string = "Empty Workspace Area"
        box.append(desc)
        
        desc2 = self.soup.new_tag('p')
        desc2.string = "This area has been created independently. Click to select this frame, then Right-click -> Insert Tag to design it."
        box.append(desc2)
        new_page.append(box)

        if existing_pages:
            existing_pages[-1].insert_after(new_page)
        else:
            main_content = self.soup.find(class_='vung-noi-dung-chinh') or self.soup.find('main') or self.soup.find(class_='content-area') or self.soup.find(class_='main-content')
            if main_content:
                main_content.append(new_page)
            else:
                body = self.soup.find('body')
                footer = self.soup.find('footer')
                if footer:
                    footer.insert_before(new_page)
                else:
                    body.append(new_page)

        self.refresh_tree()
        self.update_preview()
        
        js_sync = f"""
        (function() {{
            document.querySelectorAll('.trang-noi-dung').forEach(el => {{ el.classList.remove('trang-dang-hien-thi'); el.style.display='none'; }});
            var p = document.getElementById('{new_page_id}');
            if(p) {{ p.classList.add('trang-dang-hien-thi'); p.style.display='block'; }}
        }})();
        """
        self.web_view.page().runJavaScript(js_sync)
        
        new_id = str(id(box))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        
        self.statusBar().showMessage(msg, 6000)

    def create_linked_page(self, item, t):
        import datetime
        self.save_state_for_undo()

        new_dir = os.path.join(BASE_DIR, "New_html")
        os.makedirs(new_dir, exist_ok=True)
        existing_files = [f for f in os.listdir(new_dir) if f.lower().endswith('.html')]
        idx = len(existing_files) + 1
        date_str = datetime.datetime.now().strftime("%d%m%Y")
        
        filename = f"{idx:04d}_{date_str}_Detail.html"
        filepath = os.path.join(new_dir, filename)

        blank_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Detail Content</title>
</head>
<body style="min-height: 100vh; margin: 0; padding: 20px; font-family: sans-serif; background-color: #0f111a; color: #ffffff;">
    <div style="max-width: 1000px; margin: 0 auto; background-color: #161925; border: 1px solid #232736; padding: 30px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
        <a href="javascript:history.back()" style="display: inline-block; margin-bottom: 20px; color: #00d2ff; text-decoration: none; font-weight: bold;">⬅ Back to previous page</a>
        <h1 style="color: #00d2ff; margin-top: 0;">Detail Content...</h1>
        <p style="color: #aaa; line-height: 1.6;">You can drag and drop a Table, Layout, or Text in here to design the info page.</p>
    </div>
</body>
</html>"""

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(blank_html)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create destination page:\n{str(e)}")
            return

        rel_path = f"New_html/{filename}"
        
        if t.name == 'button':
            t.name = 'a'
            t['href'] = rel_path
            msg = f"🔗 Button transformed into a Link, pointing to: {filename}"
        elif t.name == 'a':
            t['href'] = rel_path
            msg = f"🔗 Link updated, pointing to: {filename}"
        else:

            new_a = self.soup.new_tag('a', href=rel_path)
            new_a['style'] = "text-decoration: none; color: inherit; display: block;"
            t.wrap(new_a)
            msg = f"🔗 Link tag wrapped around the outside, pointing to: {filename}"
            t = new_a 
            
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(t))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(msg, 5000)
        
        reply = QMessageBox.question(self, "Navigate to page", f"Destination page created: {filename} and link attached successfully!\n\nWould you like to open that page now to design its content?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:

            if self.current_file_path:
                self.execute_save(self.current_file_path)

            self.load_template_file(filepath)

    def create_collapsible_content(self, item, t):
        if hasattr(self, 'check_locked') and t.get('data-locked') == 'true':
            QMessageBox.information(self, "Quick Tip", "This button is Locked, so the Tool will smartly place a Hidden Content Block right below the button so as not to break your CSS structure!")

        self.save_state_for_undo()
        import random
        
        box_id = f"collapse_box_{random.randint(10000, 99999)}"
        hidden_box = self.soup.new_tag('div', id=box_id)
        hidden_box['style'] = "display: block; padding: 20px; margin-top: 5px; margin-bottom: 15px; background-color: rgba(150,150,150,0.05); border-left: 3px solid #ff9800; border-radius: 4px; width: 100%; box-sizing: border-box;"
        hidden_box.string = "Hidden content block... (Click the item above to Toggle this block). Drag and drop other tags in here!"
        
        current_style = str(t.get('style', ''))
        if 'cursor: pointer' not in current_style:
            t['style'] = current_style.strip(';') + ("; " if current_style else "") + "cursor: pointer;"
            
        t['onclick'] = f"var el = document.getElementById('{box_id}'); if(el.style.display === 'none' || el.style.display === '') {{ el.style.display = 'block'; }} else {{ el.style.display = 'none'; }}"
        t.insert_after(hidden_box)
        
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(hidden_box))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage("🔽 Hidden content block created successfully! On the live website, clicking the item above will Toggle this block.", 7000)

    def insert_inner_pagination(self, item, t):
        self.save_state_for_undo()
        import random
        from PySide6.QtWidgets import QMessageBox

        if hasattr(self, 'check_locked') and t.get('data-locked') == 'true':
            QMessageBox.warning(self, "CSS Protection", "This block is currently 🔒 LOCKED. Cannot insert Pagination inside it!")
            return

        pag_id = f"inner-pag-{random.randint(10000, 99999)}"
        
        js_pag_switch = "var p=this.closest('.pagination-wrapper');var act=this.getAttribute('data-action');var pId=this.getAttribute('data-page');var pgs=Array.from(p.querySelectorAll('.phan-trang-noi-dung'));var btns=Array.from(p.querySelectorAll('.nut-phan-trang'));var cIdx=pgs.findIndex(x=>x.style.display==='block');if(cIdx<0)cIdx=0;var nIdx=cIdx;if(act==='first')nIdx=0;if(act==='last')nIdx=pgs.length-1;if(act==='prev')nIdx=Math.max(0,cIdx-1);if(act==='next')nIdx=Math.min(pgs.length-1,cIdx+1);if(pId)nIdx=pgs.findIndex(x=>x.id===pId);if(nIdx<0)return;pgs.forEach((el,i)=>el.style.display=(i===nIdx)?'block':'none');p.querySelectorAll('.pag-dots').forEach(d=>d.remove());var aBg=btns.length>0?(btns[0].getAttribute('data-active-bg')||'#007acc'):'#007acc';btns.forEach((b,i)=>{if(i===nIdx){b.style.background=aBg;b.style.color='#fff';b.style.boxShadow='0 0 10px '+aBg;}else{b.style.background='transparent';b.style.color='inherit';b.style.boxShadow='none';}var disp=b.getAttribute('data-disp')||'inline-block';if(btns.length>5){if(i===0||i===btns.length-1||(i>=nIdx-1&&i<=nIdx+1)){b.style.display=disp;if(i===nIdx-1&&i>1){var d1=document.createElement('span');d1.className='pag-dots';d1.innerHTML='...';d1.style.padding='0 5px';b.parentNode.insertBefore(d1,b);}if(i===btns.length-1&&nIdx<btns.length-3){var d2=document.createElement('span');d2.className='pag-dots';d2.innerHTML='...';d2.style.padding='0 5px';b.parentNode.insertBefore(d2,b);}}else{b.style.display='none';}}else{b.style.display=disp;}});"

        html = f'''
        <div class="pagination-wrapper" style="width:100%; margin:20px 0; border: 1px dashed rgba(150,150,150,0.5); padding: 15px; border-radius: 8px; box-sizing: border-box;">
            <div id="{pag_id}-1" class="phan-trang-noi-dung" style="display:block; min-height:150px; width:100%; margin-bottom:20px;">
                <h3 style="margin-top:0; color:#007acc;">Page 1 Content (Internal)</h3>
                <p style="opacity:0.7;">Drag and drop Text, Table, Image... in here.</p>
            </div>
            <div id="{pag_id}-2" class="phan-trang-noi-dung" style="display:none; min-height:150px; width:100%; margin-bottom:20px;">
                <h3 style="margin-top:0; color:#007acc;">Page 2 Content (Internal)</h3>
                <p style="opacity:0.7;">This is page 2.</p>
            </div>
            <div class="pagination" style="display:flex; justify-content:center; align-items:center; gap:8px; width:100%; font-family:sans-serif;">
                <a class="nav-phan-trang" data-action="first" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&laquo;</a>
                <a class="nav-phan-trang" data-action="prev" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&lsaquo;</a>
                
                <a class="nut-phan-trang" data-page="{pag_id}-1" data-active-bg="#007acc" data-disp="inline-block" onclick="{js_pag_switch}" style="padding:8px 15px; background:#007acc; color:#fff; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer; box-shadow:0 0 10px rgba(0,122,204,0.5); border: 1px solid rgba(150,150,150,0.3);">1</a>
                <a class="nut-phan-trang" data-page="{pag_id}-2" data-active-bg="#007acc" data-disp="inline-block" onclick="{js_pag_switch}" style="padding:8px 15px; background:transparent; color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer; border: 1px solid rgba(150,150,150,0.3);">2</a>
                
                <a class="nav-phan-trang" data-action="next" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&rsaquo;</a>
                <a class="nav-phan-trang" data-action="last" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&raquo;</a>
            </div>
        </div>
        '''
        
        new_soup = self.parse_html(html)
        pag_node = new_soup.find(class_='pagination-wrapper')
        
        if t.name in ['body', 'html']: t.append(pag_node)
        else: t.append(pag_node)

        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(pag_node))
        if new_id in self.node_map:
            self.select_tree_item_by_id(new_id)
            
        self.statusBar().showMessage("🔢 Internal Pagination block inserted successfully!", 5000)

    def check_locked(self, t):

        curr = t
        while curr and curr.name not in ['body', 'html']:
            if curr.get('data-locked') == 'true': return True
            curr = curr.parent
        return False

    def toggle_lock(self, item, t):
        self.save_state_for_undo()
        if t.get('data-locked') == 'true':
            del t['data-locked']
            msg = "🔓 UNLOCKED! You can now freely insert more structure inside."
        else:
            t['data-locked'] = 'true'
            msg = "🔒 LOCKED FOR PROTECTION! Absolutely prevents inserting child tags that would break this button's CSS."
        
        self.refresh_tree()
        self.update_preview()
        new_id = str(id(t))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(msg, 5000)

    def attach_safe_link(self, item, t):
        from PySide6.QtWidgets import QInputDialog
        
        url, ok = QInputDialog.getText(self, "Attach Safe Link (Prevents breaking layout)", "Enter the Web URL or File name to download:\n(E.g.: https://google.com or document.pdf)")
        
        if ok and url:
            self.save_state_for_undo()
            
            t['onclick'] = f"window.open('{url.strip()}', '_blank');"
            
            st = str(t.get('style', '')).strip()
            if 'cursor: pointer' not in st and 'cursor:pointer' not in st:
                t['style'] = st.strip(';') + ("; " if st else "") + "cursor: pointer;"
                
            self.refresh_tree()
            self.update_preview()
            
            new_id = str(id(t))
            if new_id in self.node_map: self.select_tree_item_by_id(new_id)
            
            self.statusBar().showMessage(f"🧲 Link silently attached to tag <{t.name}>! The button remains 100% intact.", 6000)

    def edit_raw_html(self, item, t):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QMessageBox
        import copy
        
        self.save_state_for_undo()
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"🛠️ Edit HTML Directly: <{t.name}>")
        dialog.resize(900, 600)
        dialog.setStyleSheet("""
            QDialog { background-color: #1e1e1e; } 
            QPushButton { background-color: #0e639c; color: white; padding: 10px 20px; font-weight: bold; border-radius: 4px; font-size: 14px; } 
            QPushButton:hover { background-color: #1177bb; }
        """)
        
        layout = QVBoxLayout(dialog)
        
        editor = QTextEdit()
        editor.setStyleSheet("""
            background-color: #1e1e1e; 
            color: #d4d4d4; 
            font-family: 'Consolas', monospace; 
            font-size: 15px; 
            border: 2px solid #3e3e42; 
            padding: 15px;
            border-radius: 6px;
        """)
        editor.setAcceptRichText(False)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap) 
        highlighter = HTMLHighlighter(editor.document())
        
        temp_t = copy.copy(t)
        eid = temp_t.get('data-editor-id')
        if 'data-editor-id' in temp_t.attrs: del temp_t['data-editor-id']
        if 'class' in temp_t.attrs and 'editor-highlight' in temp_t['class']:
            temp_t['class'].remove('editor-highlight')
            if not temp_t['class']: del temp_t['class']
            
        pretty_html = temp_t.prettify()
        editor.setPlainText(pretty_html)
        
        layout.addWidget(editor)
        
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 SAVE AND OVERWRITE THIS TAG")
        btn_save.setStyleSheet("background-color: #28a745; font-size: 15px;")
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("background-color: #555;")
        btn_cancel.clicked.connect(dialog.reject)
        
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)
        
        def save_html():
            new_html = editor.toPlainText().strip()
            if not new_html:
                QMessageBox.warning(dialog, "Error", "HTML code cannot be empty!")
                return
            
            new_soup = self.parse_html(new_html)
            new_elements = [e for e in (new_soup.body or new_soup).children if isinstance(e, Tag)]
            
            if not new_elements:
                QMessageBox.warning(dialog, "Error", "Invalid HTML structure!")
                return
                
            new_t = new_elements[0]
            
            if eid: new_t['data-editor-id'] = eid
            
            t.replace_with(new_t)
            
            self.refresh_tree()
            
            import base64
            b64_html = base64.b64encode(str(new_t).encode('utf-8')).decode('utf-8')
            js = f"""
            (function(){{
                var el = document.querySelector('[data-editor-id="{eid}"]');
                if(el) {{
                    var temp = document.createElement('div');
                    temp.innerHTML = decodeURIComponent(escape(window.atob('{b64_html}')));
                    var newEl = temp.firstElementChild;
                    if(newEl) {{
                        el.replaceWith(newEl);
                        setTimeout(() => newEl.classList.add('editor-highlight'), 50);
                    }}
                }}
            }})();
            """
            self.web_view.page().runJavaScript(js)
            
            if eid and eid in self.node_map:
                self.select_tree_item_by_id(eid)
                
            self.statusBar().showMessage("✅ HTML code overwritten directly, successfully!", 5000)
            dialog.accept()
            
        btn_save.clicked.connect(save_html)
        dialog.exec()

    def add_hover_effect(self, item, t):
        self.save_state_for_undo()
        
        head = self.soup.find('head')
        if not head:
            head = self.soup.new_tag('head')
            if self.soup.html: self.soup.html.insert(0, head)
            
        effect_style_id = "magic-hover-effects"
        if not self.soup.find(id=effect_style_id):
            style_tag = self.soup.new_tag('style', id=effect_style_id)
            style_tag.string = """
            /* 1. Scale Up & Lift */
            .hover-scale { transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), box-shadow 0.3s ease !important; }
            .hover-scale:hover { transform: translateY(-5px) scale(1.03) !important; box-shadow: 0 15px 25px rgba(0,0,0,0.2) !important; z-index: 10; }
            
            /* 2. Glow */
            .hover-glow { transition: all 0.3s ease !important; }
            .hover-glow:hover { box-shadow: 0 0 15px #00d2ff, 0 0 30px #00d2ff !important; border-color: #00d2ff !important; z-index: 10; }
            
            /* 3. Fade */
            .hover-opacity { transition: opacity 0.3s ease !important; }
            .hover-opacity:hover { opacity: 0.6 !important; }
            
            /* 4. Multicolor Neon Glow */
            .hover-neon { transition: all 0.3s ease !important; }
            .hover-neon:hover { box-shadow: 0 0 10px #ff00ff, 0 0 20px #00ffff, 0 0 30px #00ff00 !important; border-color: #fff !important; z-index: 10; }
            
            /* 5. 3D Tilt */
            .hover-tilt { transition: transform 0.4s ease, box-shadow 0.4s ease !important; }
            .hover-tilt:hover { transform: perspective(1000px) rotateX(8deg) rotateY(-8deg) scale(1.02) !important; box-shadow: -10px 10px 20px rgba(0,0,0,0.3) !important; z-index: 10; }
            
            /* 6. Attention-grabbing Shake (Wiggle) */
            @keyframes hoverWiggle { 0% {transform: rotate(0deg);} 25% {transform: rotate(-3deg);} 50% {transform: rotate(3deg);} 75% {transform: rotate(-3deg);} 100% {transform: rotate(0deg);} }
            .hover-wiggle:hover { animation: hoverWiggle 0.4s ease-in-out infinite !important; z-index: 10; }
            
            /* 7. Grayscale -> Color (For images) */
            .hover-color { filter: grayscale(100%) !important; transition: filter 0.5s ease, transform 0.3s ease !important; }
            .hover-color:hover { filter: grayscale(0%) !important; transform: scale(1.02) !important; }
            
            /* 8. Expanded Border Outline (Outline Offset) */
            .hover-outline { transition: outline-offset 0.3s ease, outline-color 0.3s ease !important; outline: 2px solid transparent !important; outline-offset: 0px !important; }
            .hover-outline:hover { outline-color: #00d2ff !important; outline-offset: 8px !important; }
            """
            head.append(style_tag)
            
        from PySide6.QtWidgets import QInputDialog
        items = [
            "1. Scale Up & Lift (Scale & Shadow)", 
            "2. Blue Border Glow (Glow)", 
            "3. Fade (Opacity)",
            "4. 🌈 Multicolor Neon Glow (Neon)",
            "5. 🧊 3D Tilt (3D Tilt)",
            "6. 🔔 Attention-grabbing Shake (Wiggle)",
            "7. 🎨 Grayscale -> Color (For Images)",
            "8. 🔲 Expanded Border Outline (Outline Offset)"
        ]
        effect, ok = QInputDialog.getItem(self, "Select Effect", "When hovering the mouse over this tag, it will:", items, 0, False)
        
        if ok and effect:
            classes = t.get('class', [])
            if isinstance(classes, str): classes = [classes]
            
            all_hover_classes = ['hover-scale', 'hover-glow', 'hover-opacity', 'hover-neon', 'hover-tilt', 'hover-wiggle', 'hover-color', 'hover-outline']
            classes = [c for c in classes if c not in all_hover_classes]
            
            if "Scale Up" in effect: classes.append("hover-scale")
            elif "Blue Border Glow" in effect: classes.append("hover-glow")
            elif "Fade" in effect: classes.append("hover-opacity")
            elif "Neon" in effect: classes.append("hover-neon")
            elif "3D Tilt" in effect: classes.append("hover-tilt")
            elif "Shake" in effect: classes.append("hover-wiggle")
            elif "Grayscale" in effect: classes.append("hover-color")
            elif "Border Outline" in effect: classes.append("hover-outline")
            
            t['class'] = classes
            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage(f"✨ Gorgeous Hover effect applied to tag <{t.name}>!", 4000)

    def make_collapsible_menu(self, item, t):
        self.save_state_for_undo()
        
        next_sibling = t.find_next_sibling()
        
        if not next_sibling or 'sub-menu-folder' not in next_sibling.get('class', []):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Sub-item Not Found", "There is no Sub-item Folder directly below this item yet.\n\nPlease use the 'Add Sub-item (Sub-menu Folder)' feature first, before enabling this Collapse/Expand function.")
            return
            
        folder_id = next_sibling.get('id')
        if not folder_id:
            import random
            folder_id = f"sub_folder_{random.randint(1000, 9999)}"
            next_sibling['id'] = folder_id
            
        st_folder = str(next_sibling.get('style', ''))
        if 'display: none' not in st_folder:
            next_sibling['style'] = st_folder.replace('display: flex;', 'display: none;') + (";" if not st_folder.endswith(';') else "")
            
        t['onclick'] = f"var folder = document.getElementById('{folder_id}'); var icon = this.querySelector('.dropdown-icon'); if(folder.style.display === 'none') {{ folder.style.display = 'flex'; if(icon) icon.style.transform = 'rotate(0deg)'; }} else {{ folder.style.display = 'none'; if(icon) icon.style.transform = 'rotate(-90deg)'; }}"
        
        icon = t.find('span', class_='dropdown-icon')
        if icon:
            icon_st = str(icon.get('style', ''))
            icon['style'] = icon_st.strip(';') + "; transform: rotate(-90deg);"
            
        self.refresh_tree()
        self.update_preview()
        self.statusBar().showMessage("↕️ Collapse/Expand (Dropdown) feature enabled successfully!", 5000)


    def add_pagination_page(self, pag_container):
        self.save_state_for_undo()
        import random
        
        wrapper = pag_container.parent
        if not wrapper or wrapper.name in ['body', 'html'] or 'pagination-wrapper' not in wrapper.get('class', []):
            wrapper = pag_container.find_parent(class_='pagination-wrapper')
            
        if not wrapper:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Structure Error", "This pagination block is not inside a Wrapper Frame (pagination-wrapper). Please use the new Pagination template from the Library!")
            return

        page_links = wrapper.find_all('a', class_='nut-phan-trang')
        current_count = len(page_links)
        next_num = current_count + 1
        
        new_page_id = f"sub-page-pagin-{random.randint(10000, 99999)}"
        
        base_btn_style = "padding:8px 15px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;"
        active_bg = "#007acc"
        disp = "inline-block"
        if page_links:
            st = str(page_links[0].get('style', ''))
            base_btn_style = st.replace('box-shadow', 'no-shadow').replace('background:#007acc', 'background:transparent').replace('color:#fff', 'color:inherit').replace('background:#28a745', 'background:transparent')
            active_bg = page_links[0].get('data-active-bg', '#007acc')
            disp = page_links[0].get('data-disp', 'inline-block')
        
        js_pag_switch = "var p=this.closest('.pagination-wrapper');var act=this.getAttribute('data-action');var pId=this.getAttribute('data-page');var pgs=Array.from(p.querySelectorAll('.phan-trang-noi-dung'));var btns=Array.from(p.querySelectorAll('.nut-phan-trang'));var cIdx=pgs.findIndex(x=>x.style.display==='block');if(cIdx<0)cIdx=0;var nIdx=cIdx;if(act==='first')nIdx=0;if(act==='last')nIdx=pgs.length-1;if(act==='prev')nIdx=Math.max(0,cIdx-1);if(act==='next')nIdx=Math.min(pgs.length-1,cIdx+1);if(pId)nIdx=pgs.findIndex(x=>x.id===pId);if(nIdx<0)return;pgs.forEach((el,i)=>el.style.display=(i===nIdx)?'block':'none');p.querySelectorAll('.pag-dots').forEach(d=>d.remove());var aBg=btns.length>0?(btns[0].getAttribute('data-active-bg')||'#007acc'):'#007acc';btns.forEach((b,i)=>{if(i===nIdx){b.style.background=aBg;b.style.color='#fff';b.style.boxShadow='0 0 10px '+aBg;}else{b.style.background='transparent';b.style.color='inherit';b.style.boxShadow='none';}var disp=b.getAttribute('data-disp')||'inline-block';if(btns.length>5){if(i===0||i===btns.length-1||(i>=nIdx-1&&i<=nIdx+1)){b.style.display=disp;if(i===nIdx-1&&i>1){var d1=document.createElement('span');d1.className='pag-dots';d1.innerHTML='...';d1.style.padding='0 5px';b.parentNode.insertBefore(d1,b);}if(i===btns.length-1&&nIdx<btns.length-3){var d2=document.createElement('span');d2.className='pag-dots';d2.innerHTML='...';d2.style.padding='0 5px';b.parentNode.insertBefore(d2,b);}}else{b.style.display='none';}}else{b.style.display=disp;}});"

        new_btn = self.soup.new_tag('a')
        new_btn['class'] = "nut-phan-trang"
        new_btn['data-page'] = new_page_id
        new_btn['data-active-bg'] = active_bg
        new_btn['data-disp'] = disp
        new_btn['style'] = base_btn_style
        new_btn['onclick'] = js_pag_switch
        new_btn.string = str(next_num)
        
        btn_container = wrapper.find(class_='pagination') or pag_container
        if page_links:
            page_links[-1].insert_after(new_btn)
        else:
            btn_container.append(new_btn)
            
        new_content_div = self.soup.new_tag('div', id=new_page_id)
        new_content_div['class'] = ["phan-trang-noi-dung"]
        new_content_div['style'] = f"display: none; min-height: 150px; border: 2px dashed {active_bg}; padding: 20px; border-radius: 8px; margin-bottom: 20px; width: 100%; box-sizing: border-box;"
        
        title = self.soup.new_tag('h3')
        title['style'] = f"margin-top: 0; color: {active_bg};"
        title.string = f"Page {next_num} Content"
        new_content_div.append(title)
        
        desc = self.soup.new_tag('p')
        desc.string = f"Empty area of page {next_num}. Drag and drop content or insert a table in here."
        new_content_div.append(desc)

        btn_container.insert_before(new_content_div)

        self.refresh_tree()
        self.update_preview()

        js_init = f"var wrapper = document.getElementById('{new_page_id}').closest('.pagination-wrapper'); if(wrapper) {{ var activeBtn = wrapper.querySelector('.nut-phan-trang[style*=\"{active_bg}\"]'); if(!activeBtn) activeBtn = wrapper.querySelector('.nut-phan-trang'); if(activeBtn) activeBtn.click(); }}"
        self.web_view.page().runJavaScript(js_init)
        
        new_id = str(id(new_content_div))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        
        self.statusBar().showMessage(f"📄 Page {next_num} generated safely! (Automatically collapses to ... once past 5 pages)", 4000)

    def add_blank_page_to_menu(self, item, t):
        from PySide6.QtWidgets import QMessageBox
        
        target_btn = t
        if t.name == 'li':
            a_tag = t.find('a')
            if a_tag: target_btn = a_tag

        if 'pagination' in target_btn.get('class', []) or target_btn.find_parent(class_='pagination-wrapper') or target_btn.find_parent(class_='pagination') or 'nut-phan-trang' in target_btn.get('class', []):
            QMessageBox.warning(self, "Structure Protection", "The Pagination area already has its own separate page-switching algorithm (collapsing ...).\nAbsolutely do not use the 'Create Blank Page' function here, to avoid overwriting and breaking the Pagination set!")
            return
            
        self.save_state_for_undo()
        import random

        new_page_id = f"trang-noi-dung-{random.randint(10000, 99999)}"

        classes = target_btn.get('class', [])
        if isinstance(classes, str): classes = [classes]
        if 'nut-chuyen-trang' not in classes: classes.append('nut-chuyen-trang')
        target_btn['class'] = classes
        target_btn['data-trang'] = new_page_id

        js_tab_switch = "var tId=this.getAttribute('data-trang'); document.querySelectorAll('.trang-noi-dung').forEach(function(el){el.classList.remove('trang-dang-hien-thi'); el.style.display='none';}); var target=document.getElementById(tId); if(target){target.classList.add('trang-dang-hien-thi'); target.style.display='block';} document.querySelectorAll('.nut-chuyen-trang').forEach(function(btn){btn.classList.remove('menu-dang-chon'); if(btn.getAttribute('data-trang')===tId) btn.classList.add('menu-dang-chon');});"

        st = str(target_btn.get('style', ''))
        if 'cursor: pointer' not in st and 'cursor:pointer' not in st:
            target_btn['style'] = st.strip(';') + ("; " if st else "") + "cursor: pointer;"
        target_btn['onclick'] = js_tab_switch

        new_page = self.soup.new_tag('div', id=new_page_id)
        new_page['class'] = ["trang-noi-dung", "trang-dang-hien-thi"]
        new_page['style'] = "display: block; min-height: 300px; padding: 20px; border: 2px dashed #007acc; border-radius: 8px; margin-top: 15px; width: 100%; box-sizing: border-box;"

        title = self.soup.new_tag('h2')
        title['style'] = "color: #007acc; margin-top: 0;"
        
        parent_name = target_btn.get_text(strip=True).replace('▼', '').strip()
        if not parent_name: parent_name = "New Tab"
        title.string = f"Content: {parent_name}"
        new_page.append(title)

        desc = self.soup.new_tag('p')
        desc.string = "The new content page area has been linked to the button you just selected. Drag and drop tags from the library in here to design it."
        new_page.append(desc)

        for el in self.soup.find_all(class_='trang-noi-dung'):
            cls = el.get('class', [])
            if isinstance(cls, str): cls = [cls]
            if 'trang-dang-hien-thi' in cls: cls.remove('trang-dang-hien-thi')
            el['class'] = cls
            est = str(el.get('style', ''))
            if 'display: block' in est: el['style'] = est.replace('display: block', 'display: none')
            elif 'display' not in est: el['style'] = est.strip(';') + ("; " if est else "") + "display: none;"

        for btn in self.soup.find_all(class_='menu-dang-chon'):
            b_cls = btn.get('class', [])
            if isinstance(b_cls, str): b_cls = [b_cls]
            if 'menu-dang-chon' in b_cls:
                b_cls.remove('menu-dang-chon')
                btn['class'] = b_cls

        t_cls = target_btn.get('class', [])
        if isinstance(t_cls, str): t_cls = [t_cls]
        if 'menu-dang-chon' not in t_cls:
            t_cls.append('menu-dang-chon')
            target_btn['class'] = t_cls

        main_content = self.soup.find(class_='main-content') or self.soup.find(class_='vung-noi-dung-chinh') or self.soup.find('main')
        if main_content:
            main_content.append(new_page)
        else:
            self.soup.find('body').append(new_page)

        self.refresh_tree()
        self.update_preview()

        new_id = str(id(new_page))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        
        self.statusBar().showMessage(f"📄 Blank Page created and successfully linked to button: {parent_name}!", 6000)

    def add_sibling_category(self, item, t):
        self.save_state_for_undo()
        
        target = t
        li_wrapper = target if target.name == 'li' else target.find_parent('li')
        is_breadcrumb = False
        
        if li_wrapper and li_wrapper.parent and li_wrapper.parent.name in ['ol', 'ul']:
            is_breadcrumb = True
            target = li_wrapper
        elif target.name in ['span', 'i', 'b', 'strong'] and target.parent and target.parent.name == 'a':
            target = target.parent

        if not target or target.name in ['body', 'html']:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", "Cannot add a sibling category at this position.")
            return

        new_cat = self.clone_node(target)

        for tag in [new_cat] + new_cat.find_all(True):
            if tag.has_attr('data-trang'): del tag['data-trang']
            if tag.has_attr('onclick'): del tag['onclick']
            cls = tag.get('class', [])
            if isinstance(cls, str): cls = [cls]
            if 'menu-dang-chon' in cls: cls.remove('menu-dang-chon')
            tag['class'] = cls

        text_nodes = list(new_cat.find_all(string=True))
        for s in text_nodes:
            if s.strip() and s.strip() != '/':
                s.replace_with("New category")
                break

        if is_breadcrumb:
            separator = self.soup.new_tag('li')
            separator['style'] = "margin-right:10px; opacity:0.5;"
            separator.string = "/"
            target.insert_after(separator)
            separator.insert_after(new_cat)
        else:
            target.insert_after(new_cat)

        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(new_cat))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        
        self.statusBar().showMessage("➖ Sibling Category added!", 4000)

    def copy_element(self, item, t): 
        self.clipboard_node = self.clone_node(t)
        self.statusBar().showMessage(f"📋 Tag <{t.name}> copied to clipboard!", 3000)

    def cut_element(self, item, t):
        self.save_state_for_undo()
        self.clipboard_node = self.clone_node(t)
        t.decompose()
        self.refresh_tree()
        self.update_preview()
        self.statusBar().showMessage(f"✂️ Tag <{t.name}> cut!", 3000)

    def paste_element(self, item, t, mode):
        if not self.clipboard_node: return
        self.save_state_for_undo()
        pt = self.clone_node(self.clipboard_node) # Clone again from clipboard so it can be pasted multiple times
        if mode == "inside": t.append(pt)
        else: t.insert_after(pt)
        self.refresh_tree()
        self.update_preview()
        self.statusBar().showMessage("📌 Pasted successfully!", 3000)

    def delete_html_element(self, item, t):
        if QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete tag <{t.name}>?") == QMessageBox.StandardButton.Yes:
            self.save_state_for_undo()
            t.decompose()
            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage("🗑️ Object deleted!", 3000)

    def search_dom_tree(self, text):
        if not self.tree.topLevelItemCount(): return
        query = text.lower()
        
        def search_recursive(item):
            match = False
            if query in item.text(0).lower(): match = True
            
            child_match = False
            for i in range(item.childCount()):
                if search_recursive(item.child(i)): child_match = True
                
            item.setHidden(not (match or child_match))
            
            if query and child_match: item.setExpanded(True)
            return match or child_match

        search_recursive(self.tree.topLevelItem(0))
        
        if not query:
            self.tree.collapseAll()
            self.tree.topLevelItem(0).setExpanded(True)

    def simulate_device(self, mode):
        pass

    def change_zoom(self, zoom_str):
        try:
            user_zoom = float(zoom_str.replace('%', '')) / 100.0
            
            dpi_scale = self.devicePixelRatioF()
            
            true_zoom_factor = user_zoom / dpi_scale
            
            self.web_view.setZoomFactor(true_zoom_factor)
            self.statusBar().showMessage(f"🔍 Web Zoom: {zoom_str} (Automatically compensated for Windows' {dpi_scale}x scaling)", 4000)
        except Exception:
            self.web_view.setZoomFactor(1.0)
            self.cb_zoom.setCurrentText("100%")


    def refresh_library(self):
        from PySide6.QtWidgets import QListWidget
        comp_dir = os.path.join(BASE_DIR, 'components')
        if not os.path.exists(comp_dir):
            os.makedirs(comp_dir)
            
        if hasattr(self, 'list_library'):
            self.list_library.clear()

            for f_name in os.listdir(comp_dir):
                if f_name.lower().endswith(('.html', '.htm')):
                    self.list_library.addItem(f_name)
                    
            self.statusBar().showMessage(f"📦 Loaded {self.list_library.count()} interface blocks from the components/ folder", 3000)


    def insert_from_library(self):
        item = self.list_library.currentItem()
        if not item:
            QMessageBox.warning(self, "No block selected", "Please select an HTML block from the list to insert!")
            return
            
        html_filename = item.text()
        base_name = os.path.splitext(html_filename)[0]
        
        html_path = os.path.join(BASE_DIR, 'components', html_filename)
        css_path = os.path.join(BASE_DIR, 'components', f"{base_name}.css")
        
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                final_content = f.read()
            
            has_css = False
            if os.path.exists(css_path):
                with open(css_path, 'r', encoding='utf-8') as f:
                    css_content = f.read()
                
                if css_content.strip():
                    final_content = f"<style>\n{css_content.strip()}\n</style>\n" + final_content
                    has_css = True
            
            self.insert_quick_component(final_content)
            
            if has_css:
                self.statusBar().showMessage(f"✅ Inserted block [{html_filename}] + Automatically attached matching CSS!", 4000)
            else:
                self.statusBar().showMessage(f"✅ Inserted block [{html_filename}] (No accompanying CSS effect).", 4000)
                
        except Exception as e:
            QMessageBox.critical(self, "File Read Error", f"Could not load this block:\n{str(e)}")


    def show_template_gallery(self):
        self.view_stack.setCurrentIndex(1)
        
        tpl_dir = os.path.join(BASE_DIR, 'templates')
        os.makedirs(tpl_dir, exist_ok=True)
        self.template_files = [f for f in os.listdir(tpl_dir) if f.lower().endswith(('.html', '.htm'))]
        
        self.current_tpl_page = 0
        self.update_gallery_ui()

    def update_gallery_ui(self):
        from PySide6.QtCore import QUrl
        total_files = len(self.template_files)
        total_pages = (total_files + 3) // 4
        if total_pages == 0: total_pages = 1
        
        self.lbl_page_tpl.setText(f"Trang {self.current_tpl_page + 1} / {total_pages}")
        self.btn_prev_tpl.setEnabled(self.current_tpl_page > 0)
        self.btn_next_tpl.setEnabled(self.current_tpl_page < total_pages - 1)
        
        start_idx = self.current_tpl_page * 4
        tpl_dir = os.path.join(BASE_DIR, 'templates')
        
        for i in range(4):
            idx = start_idx + i
            if idx < total_files:
                file_name = self.template_files[idx]
                file_path = os.path.join(tpl_dir, file_name)

                self.mini_views[i].load(QUrl.fromLocalFile(file_path))

                try: self.mini_overlays[i].clicked.disconnect() 
                except: pass
                
                self.mini_overlays[i].setText(file_name.replace('.html', '').upper())
                self.mini_overlays[i].clicked.connect(lambda checked=False, p=file_path: self.load_template_file(p))
                
                self.mini_views[i].parent().show()
            else:
                self.mini_views[i].parent().hide()

    def prev_template_page(self):
        if self.current_tpl_page > 0:
            self.current_tpl_page -= 1
            self.update_gallery_ui()

    def next_template_page(self):
        total_pages = (len(self.template_files) + 3) // 4
        if self.current_tpl_page < total_pages - 1:
            self.current_tpl_page += 1
            self.update_gallery_ui()
            
    def load_template_file(self, filepath):

        self.view_stack.setCurrentIndex(0) 
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                self.soup = self.parse_html(f.read())

            for s in self.soup.find_all('script'):
                if not s.has_attr('src') and not s.has_attr('id') and s.string and "EDITOR_SCROLL" in s.string:
                    s.decompose()
                    
            self.current_file_path = os.path.abspath(filepath)
            if hasattr(self, 'undo_stack'): self.undo_stack.clear()
            if hasattr(self, 'redo_stack'): self.redo_stack.clear()
            
            self.lbl_current_file.setText(f"Viewing: <b>{os.path.basename(filepath)}</b>")
            self.refresh_tree(); self.update_preview()
            self.statusBar().showMessage("📑 Template interface loaded successfully!", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Template Load Error", f"Could not read template file:\n{str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UniversalHTMLEditor()
    window.show()
    sys.exit(app.exec())