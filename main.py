import sys, os, json, copy, zipfile, tempfile, shutil, urllib.parse, base64
from bs4 import BeautifulSoup, Tag, NavigableString
from PySide6.QtWidgets import (QApplication, QMainWindow, QSplitter, QWidget, 
                               QVBoxLayout, QHBoxLayout, QFormLayout, QTreeWidget, QTreeWidgetItem,
                               QLineEdit, QTextEdit, QPushButton, QMessageBox, QFileDialog, QLabel, QMenu, QSizePolicy,
                               QAbstractItemView, QColorDialog, QTabWidget, QGroupBox, QGridLayout, QComboBox, QCheckBox,
                               QListWidget)
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
        self.main_window.statusBar().showMessage("🔄 Swapped tag positions and updated HTML!", 3000)

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
                self.main_window.web_view.setFocus()
                
            elif message.startswith("EDITOR_EDIT_MODE:"):
                self.main_window.web_view.setFocus()
                
            elif message.startswith("EDITOR_OPEN_LINK:"):
                url = message.split("EDITOR_OPEN_LINK:")[1]
                QDesktopServices.openUrl(QUrl(url))
            elif message.startswith("EDITOR_HINT:"):
                self.main_window.statusBar().showMessage(message.split("EDITOR_HINT:")[1], 4000)
            
            elif message.startswith("EDITOR_CONTEXT:"):
                eid = message.split("EDITOR_CONTEXT:")[1]
                self.main_window.select_tree_item_by_id(eid)
                self.main_window.web_view.setFocus()
                self.main_window.show_context_menu(QCursor.pos(), from_web=True)
            
            elif message.startswith("EDITOR_RESIZE:"):
                try:
                    data = message.split("EDITOR_RESIZE:")[1]
                    eid, w, h = data.split("|")
                    self.main_window.sync_resize_from_web(eid, w, h)
                except Exception:
                    pass

            elif message.startswith("EDITOR_DRAG_POS:"):
                try:
                    data = message.split("EDITOR_DRAG_POS:")[1]
                    eid, left, top = data.split("|")
                    self.main_window.sync_drag_pos_from_web(eid, left, top)
                except Exception:
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
        self.setWindowTitle("html_Designer_LTH - No-Code Designer v6.5 (Ultimate Layout)")
        self.resize(1200, 950)
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
            
            QSplitter::handle { background-color: #3e3e42; }
            QSplitter::handle:horizontal { width: 4px; }
            QSplitter::handle:vertical { 
                height: 8px; 
                background-color: #252526; 
                border-top: 1px solid #3e3e42; 
                border-bottom: 1px solid #3e3e42; 
                margin: 2px 0;
            }
            QSplitter::handle:vertical:hover { background-color: #007acc; }
            
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
            
        sc_inc_font = QShortcut(QKeySequence("Ctrl+]"), self)
        sc_inc_font.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_inc_font.activated.connect(lambda: self.kbd_adjust_font(2))

        sc_dec_font = QShortcut(QKeySequence("Ctrl+["), self)
        sc_dec_font.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_dec_font.activated.connect(lambda: self.kbd_adjust_font(-2))

        sc_save = QShortcut(QKeySequence("Ctrl+S"), self)
        sc_save.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_save.activated.connect(self.kbd_save)
        
        sc_save_as = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        sc_save_as.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_save_as.activated.connect(self.kbd_save_as)
        
        self.statusBar().showMessage("Ready - Undo (Ctrl+Z) & Save (Ctrl+S) shortcuts enabled")

        self.statusBar().setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.statusBar().setFixedHeight(25)
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)

        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_layout.setSpacing(10)
        
        left_panel.setMinimumWidth(550)
        left_panel.setMaximumWidth(600)

        top_left_layout = QHBoxLayout(); top_left_layout.setContentsMargins(0,0,0,0)
        self.btn_open = QPushButton("📂 Open File"); self.btn_open.clicked.connect(self.load_file_dialog)
        
        self.btn_template = QPushButton("📑 HTML Templates")
        self.btn_template.setStyleSheet("background-color: #d7ba7d; color: #1e1e1e; font-weight: bold;")
        self.btn_template.clicked.connect(self.show_template_gallery)

        self.inp_search_dom = QLineEdit(); self.inp_search_dom.setPlaceholderText("🔍 Quick tag search (ID, Class...)")
        self.inp_search_dom.textChanged.connect(self.search_dom_tree)
        
        top_left_layout.addWidget(self.btn_open)
        top_left_layout.addWidget(self.btn_template) 
        top_left_layout.addWidget(self.inp_search_dom, stretch=1)
        left_layout.addLayout(top_left_layout)

        self.setup_quick_components_ui(left_layout)
        
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setChildrenCollapsible(False)
        left_layout.addWidget(left_splitter, stretch=1)

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

        self.lbl_breadcrumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.lbl_breadcrumb.setFixedHeight(45)
        
        tree_layout.addWidget(self.lbl_breadcrumb)
        left_splitter.addWidget(tree_container)

        bottom_container = QWidget(); bottom_layout = QVBoxLayout(bottom_container); bottom_layout.setContentsMargins(0,0,0,0)
        bottom_container.setMinimumHeight(150)
        self.tabs = QTabWidget(); bottom_layout.addWidget(self.tabs, stretch=1)

        def make_scrollable(widget):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.inp_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        
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
                        value: '<!-- Select a tag to view HTML code -->',
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
        
        self.btn_bg_color = QPushButton("🎨 Background"); self.btn_bg_color.clicked.connect(self.pick_bg_color)
        self.btn_text_color = QPushButton("🔤 Text Color"); self.btn_text_color.clicked.connect(self.pick_text_color)
        self.btn_browse_href = QPushButton("🔗"); self.btn_browse_href.clicked.connect(self.browse_href_file)
        self.btn_browse_src = QPushButton("🖼️"); self.btn_browse_src.clicked.connect(self.browse_src_file)
        for btn in [self.btn_browse_href, self.btn_browse_src]: btn.setFixedSize(30, 30)

        tab_config = QWidget(); form_config = QFormLayout(tab_config); form_config.setContentsMargins(15, 15, 15, 15)
        form_config.addRow("Tag Name:", self.inp_tag); form_config.addRow("ID:", self.inp_id)
        form_config.addRow("Class:", self.inp_class); form_config.addRow("Data-Page:", self.inp_data_trang)
        
        self.inp_form_action = QLineEdit(); self.inp_form_action.setPlaceholderText("API Link (e.g., https://formspree.io/f/...)")
        self.inp_form_action.setStyleSheet(active_style); self.inp_form_action.editingFinished.connect(self.apply_changes)
        
        self.inp_form_method = QComboBox(); self.inp_form_method.addItems(["POST", "GET"]); self.inp_form_method.setStyleSheet(active_style)
        self.inp_form_method.currentTextChanged.connect(self.apply_changes)
        
        self.lbl_form = QLabel("Form Config:")
        self.lbl_form.setStyleSheet("color: #ff9800; font-weight: bold;")
        self.w_form = QWidget(); form_action_layout = QHBoxLayout(self.w_form); form_action_layout.setContentsMargins(0,0,0,0)
        form_action_layout.addWidget(self.inp_form_method)
        form_action_layout.addWidget(self.inp_form_action, stretch=1)
        form_config.addRow(self.lbl_form, self.w_form)
        self.lbl_form.setVisible(False); self.w_form.setVisible(False)
        
        self.lbl_href = QLabel("Href (Link):")
        self.w_href = QWidget(); href_layout = QHBoxLayout(self.w_href); href_layout.setContentsMargins(0,0,0,0)
        href_layout.addWidget(self.inp_href)
        href_layout.addWidget(self.btn_browse_href)
        
        self.btn_make_link = QPushButton("🪄 Create Link")
        self.btn_make_link.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        self.btn_make_link.clicked.connect(self.convert_to_link)
        href_layout.addWidget(self.btn_make_link)
        form_config.addRow(self.lbl_href, self.w_href)
        
        self.lbl_src = QLabel("Src (Image):")
        self.w_src = QWidget(); src_layout = QHBoxLayout(self.w_src); src_layout.setContentsMargins(0,0,0,0)
        src_layout.addWidget(self.inp_src); src_layout.addWidget(self.btn_browse_src)
        form_config.addRow(self.lbl_src, self.w_src)
        
        self.chk_img_responsive = QCheckBox("🛡️ Force image to fit container (Prevent layout breakage)")
        self.chk_img_responsive.setStyleSheet("color: #28a745; font-weight: bold; margin-bottom: 5px;")
        form_config.addRow("", self.chk_img_responsive)
        self.tabs.addTab(make_scrollable(tab_config), "⚙️ Config")

        tab_style = QWidget(); style_layout = QVBoxLayout(tab_style); style_layout.setContentsMargins(15, 10, 15, 10)
        css_group = QGroupBox("📏 Dimensions & Margins"); css_grid = QGridLayout(css_group)
        self.css_width = QLineEdit(); self.css_width.setPlaceholderText("e.g., 100px, 100%")
        self.css_height = QLineEdit(); self.css_height.setPlaceholderText("e.g., 50px, auto")
        self.css_padding = QLineEdit(); self.css_padding.setPlaceholderText("Inner (e.g., 10px 20px)")
        self.css_margin = QLineEdit(); self.css_margin.setPlaceholderText("Outer (e.g., 0 auto)")
        self.css_display = QComboBox(); self.css_display.addItems(["(Default)", "block", "inline-block", "flex", "grid", "none"])

        css_grid.addWidget(QLabel("Width (W):"), 0, 0); css_grid.addWidget(self.css_width, 0, 1)
        css_grid.addWidget(QLabel("Height (H):"), 0, 2); css_grid.addWidget(self.css_height, 0, 3)
        css_grid.addWidget(QLabel("Padding:"), 1, 0); css_grid.addWidget(self.css_padding, 1, 1)
        css_grid.addWidget(QLabel("Margin:"), 1, 2); css_grid.addWidget(self.css_margin, 1, 3)
        css_grid.addWidget(QLabel("Display:"), 2, 0); css_grid.addWidget(self.css_display, 2, 1, 1, 3)
        style_layout.addWidget(css_group)
        color_layout = QHBoxLayout(); color_layout.addWidget(self.btn_bg_color); color_layout.addWidget(self.btn_text_color)
        style_layout.addLayout(color_layout)
        style_layout.addWidget(QLabel("<b>Raw CSS (Line by line):</b>"))
        style_layout.addWidget(self.inp_style, stretch=1)
        
        self.btn_apply_css = QPushButton("✔️ APPLY CSS TO PREVIEW")
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
        self.btn_refresh_lib = QPushButton("🔄 Refresh List")
        self.btn_refresh_lib.clicked.connect(self.refresh_library)
        lib_top.addWidget(QLabel("<b>Source: /components/</b>"), stretch=1)
        lib_top.addWidget(self.btn_refresh_lib)
        
        self.list_library = QTreeWidget()
        self.list_library.setHeaderHidden(True)
        self.list_library.setStyleSheet("QTreeWidget { background: #1e1e1e; border: 1px solid #3e3e42; color: #4fc1ff; font-size: 14px; } QTreeWidget::item { padding: 8px; border-bottom: 1px solid #333; } QTreeWidget::item:selected { background: #094771; color: white; font-weight: bold; }")
        
        self.btn_insert_lib = QPushButton("➕ INSERT SELECTED BLOCK INTO LAYOUT")
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
        
        self.btn_zip = QPushButton("📦 Export ZIP")
        self.btn_zip.setStyleSheet("background-color: #6c757d; font-weight: bold;")
        self.btn_zip.clicked.connect(self.export_project_to_zip)
        
        action_layout.addWidget(btn_apply, stretch=1); action_layout.addWidget(self.btn_save, stretch=1); action_layout.addWidget(self.btn_zip, stretch=1)
        
        self.btn_export_prod = QPushButton("🚀 EXPORT PRODUCTION (Extract CSS & Optimize)")
        self.btn_export_prod.setStyleSheet("background-color: #e83e8c; color: white; font-weight: bold; font-size: 14px; padding: 10px; margin-top: 5px; border-radius: 4px;")
        self.btn_export_prod.clicked.connect(self.export_production_zip)
        
        bottom_layout.addLayout(action_layout)
        bottom_layout.addWidget(self.btn_export_prod)
        
        left_splitter.addWidget(bottom_container)
        left_splitter.setSizes([200, 750])

        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel); right_layout.setContentsMargins(0, 0, 0, 0)
        
        device_toolbar = QHBoxLayout(); device_toolbar.setContentsMargins(10, 5, 10, 5)
        self.lbl_current_file = QLabel("No file opened...")
        self.lbl_current_file.setStyleSheet("padding: 5px; background: #333; font-weight: bold; border-radius: 4px;")
        
        self.lbl_current_file.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_current_file.setMinimumWidth(150)
        self.lbl_current_file.setMaximumWidth(250)
        
        self.btn_desktop = QPushButton("💻 Desktop")
        self.btn_mobile = QPushButton("📱 Mobile")
        self.btn_desktop.setToolTip("View full screen")
        self.btn_mobile.setToolTip("Simulate Mobile width (414px)")
        
        self.btn_desktop.clicked.connect(lambda: self.simulate_device("desktop"))
        self.btn_mobile.clicked.connect(lambda: self.simulate_device("mobile"))
        
        self.btn_deselect = QPushButton("🚫 Esc")
        self.btn_deselect.setToolTip("Deselect, cancel text editing")
        self.btn_deselect.clicked.connect(self.clear_selection)
        
        self.btn_refresh_view = QPushButton("🔄 Reload")
        self.btn_refresh_view.clicked.connect(self.update_preview)
        
        self.btn_open_browser = QPushButton("🌍 Web")
        self.btn_open_browser.setToolTip("Open in external browser")
        self.btn_open_browser.clicked.connect(self.open_in_external_browser)
        
        for btn in [self.btn_deselect, self.btn_refresh_view, self.btn_open_browser, self.btn_desktop, self.btn_mobile]:
            btn.setStyleSheet("background: #4d4d4d; padding: 5px 10px; border-radius: 4px; font-weight: bold; color: white;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
        self.btn_open_browser.setStyleSheet("background: #28a745; padding: 5px 10px; border-radius: 4px; font-weight: bold; color: white;")
        self.btn_desktop.setStyleSheet("background: #007acc; padding: 5px 10px; border-radius: 4px; font-weight: bold; color: white;")
        
        sc_esc = QShortcut(QKeySequence("Esc"), self)
        sc_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_esc.activated.connect(self.clear_selection)
        
        self.cb_zoom = QComboBox()
        self.cb_zoom.addItems(["75%", "100%", "110%", "120%"])
        self.cb_zoom.setCurrentText("100%")
        self.cb_zoom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_zoom.setStyleSheet("QComboBox { background: #333; padding: 4px 5px; border-radius: 4px; font-weight: bold; color: white; border: 1px solid #555; }")
        self.cb_zoom.currentTextChanged.connect(self.change_zoom)

        self.btn_undo = QPushButton("⏪ Undo")
        self.btn_undo.clicked.connect(self.undo_action)
        self.btn_redo = QPushButton("⏩ Redo")
        self.btn_redo.clicked.connect(self.redo_action)
        
        for btn in [self.btn_undo, self.btn_redo]:
            btn.setStyleSheet("background: #0e639c; padding: 5px 10px; border-radius: 4px; font-weight: bold; color: white;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        sc_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        sc_redo.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_redo.activated.connect(self.redo_action)

        self.is_edit_mode = True
        self.btn_toggle_mode = QPushButton("🛠️ Edit / 👁️ Preview")
        self.btn_toggle_mode.setToolTip("Click to toggle between Edit Mode and Preview Mode")
        self.btn_toggle_mode.setStyleSheet("background-color: #d7ba7d; color: #1e1e1e; font-weight: bold; padding: 5px 10px; border-radius: 4px;")
        self.btn_toggle_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_mode.clicked.connect(self.toggle_view_mode)

        device_toolbar.addWidget(self.lbl_current_file)
        device_toolbar.addWidget(self.btn_desktop)
        device_toolbar.addWidget(self.btn_mobile)
        device_toolbar.addWidget(self.btn_refresh_view)
        device_toolbar.addWidget(self.btn_open_browser)
        device_toolbar.addWidget(self.btn_deselect)
        
        device_toolbar.addStretch(1) 
        device_toolbar.addWidget(self.btn_toggle_mode)
        device_toolbar.addStretch(1)

        device_toolbar.addWidget(self.btn_undo)
        device_toolbar.addWidget(self.btn_redo)
        
        device_toolbar.addWidget(QLabel("🔍 Zoom:"))
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
        self.view_stack.addWidget(self.web_container)

        self.gallery_widget = QWidget()
        self.gallery_widget.setStyleSheet("background-color: #1e1e1e;")
        gallery_layout = QVBoxLayout(self.gallery_widget)
        
        tpl_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.tpl_tree = QTreeWidget()
        self.tpl_tree.setHeaderLabel("📂 HTML Templates Directory")
        self.tpl_tree.setStyleSheet("""
            QTreeWidget { background: #252526; border: 1px solid #3e3e42; color: #d4d4d4; font-size: 14px; }
            QTreeWidget::item { padding: 8px; border-bottom: 1px solid #333; }
            QTreeWidget::item:selected { background: #094771; color: white; font-weight: bold; }
            QHeaderView::section {
                background-color: #2d2d30;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #3e3e42;
                font-weight: bold;
                font-size: 13px;
            }
        """)
        self.tpl_tree.itemClicked.connect(self.on_tpl_tree_clicked)
        tpl_splitter.addWidget(self.tpl_tree)

        right_tpl = QWidget()
        right_tpl_layout = QVBoxLayout(right_tpl)
        right_tpl_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_tpl_info = QLabel("📌 Select a template on the left to preview")
        self.lbl_tpl_info.setStyleSheet("background: #252526; color: #ce9178; font-weight: bold; padding: 10px; border: 1px solid #3e3e42; font-size: 14px;")
        self.lbl_tpl_info.setWordWrap(True)
        
        self.tpl_preview = QWebEngineView()
        self.tpl_preview.setStyleSheet("background: #111111;")
        
        self.btn_use_tpl = QPushButton("✔️ USE THIS TEMPLATE")
        self.btn_use_tpl.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 12px; font-size: 14px; border-radius: 4px;")
        self.btn_use_tpl.setEnabled(False)
        self.btn_use_tpl.clicked.connect(self.load_selected_template)
        
        right_tpl_layout.addWidget(self.lbl_tpl_info)
        right_tpl_layout.addWidget(self.tpl_preview, stretch=1)
        right_tpl_layout.addWidget(self.btn_use_tpl)
        
        tpl_splitter.addWidget(right_tpl)
        tpl_splitter.setSizes([350, 850])
        gallery_layout.addWidget(tpl_splitter)
        
        self.view_stack.addWidget(self.gallery_widget) 
        
        self.view_stack.setCurrentIndex(0)
        self.selected_tpl_path = None
        self.is_dirty = False 

        main_splitter.addWidget(left_panel); main_splitter.addWidget(right_panel)

        main_splitter.setSizes([400, 1200])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        
        self.clear_form()
        self.refresh_library()
        
        self.change_zoom(self.cb_zoom.currentText())

    def toggle_view_mode(self):
        self.is_edit_mode = not getattr(self, 'is_edit_mode', True)
        if self.is_edit_mode:
            self.btn_toggle_mode.setText("🛠️ EDIT MODE (Click to Preview)")
            self.btn_toggle_mode.setStyleSheet("background-color: #d7ba7d; color: #1e1e1e; font-weight: bold; padding: 5px 15px; border-radius: 4px; font-size: 14px;")
            self.web_view.page().runJavaScript("window.isEditMode = true;")
            self.statusBar().showMessage("🛠️ IN EDIT MODE: Right-click, tag selection, and text editing are enabled.", 4000)
        else:
            self.btn_toggle_mode.setText("👁️ PREVIEW MODE (Click to Edit)")
            self.btn_toggle_mode.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 5px 15px; border-radius: 4px; font-size: 14px;")
            self.clear_selection()
            self.web_view.page().runJavaScript("window.isEditMode = false; document.querySelectorAll('.editor-highlight').forEach(e => e.classList.remove('editor-highlight'));")
            self.statusBar().showMessage("👁️ IN PREVIEW MODE: You can click tabs, accordions, links... just like a live webpage!", 4000)

    def clear_selection(self):
        self.current_node = None
        self.last_active_eid = ""
        self.tree.clearSelection()
        self.clear_form()
        self.lbl_breadcrumb.setText("📌 No tag selected")

        js_clear = """
        (function() {
            document.querySelectorAll('.editor-highlight, .editor-hover').forEach(e => {
                e.classList.remove('editor-highlight', 'editor-hover');
            });
            if (window.currentEditingEl) {
                window.currentEditingEl.removeAttribute('contenteditable');
                window.currentEditingEl = null;
            }
            window.getSelection().removeAllRanges();
            if (document.activeElement) {
                document.activeElement.blur();
            }
        })();
        """
        self.web_view.page().runJavaScript(js_clear)
        self.statusBar().showMessage("🚫 Selection cleared and layout released!", 3000)

    def open_in_external_browser(self):
        if not self.current_file_path or not os.path.exists(self.current_file_path):
            QMessageBox.warning(self, "No file found", "You need to Open or Save a file before viewing it in an external browser!")
            return
        
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_file_path))
        self.statusBar().showMessage("🌍 Opened file in default browser!", 3000)

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
        p = self.get_relative_path("Select File", "Documents (*.html *.htm *.md);;All files (*.*)")
        if p: self.inp_href.setText(p)

    def browse_src_file(self):
        p = self.get_relative_path("Select Image", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if p: self.inp_src.setText(p)

    def save_state_for_undo(self):
        self.is_dirty = True
        
        if not hasattr(self, 'undo_stack'): self.undo_stack = []
        if not hasattr(self, 'redo_stack'): self.redo_stack = []
        if self.soup:
            self.undo_stack.append(str(self.soup))
            if len(self.undo_stack) > 50: self.undo_stack.pop(0)
            self.redo_stack.clear()

    def undo_action(self):
        if not hasattr(self, 'undo_stack') or not self.undo_stack:
            self.statusBar().showMessage("Oldest state reached, cannot Undo further!", 3000)
            return
        if not hasattr(self, 'redo_stack'): self.redo_stack = []
        
        self.redo_stack.append(str(self.soup))
        self.soup = self.parse_html(self.undo_stack.pop())
        self.refresh_tree(); self.update_preview()
        self.statusBar().showMessage("⏪ Undo successful!", 3000)

    def redo_action(self):
        if not hasattr(self, 'redo_stack') or not self.redo_stack:
            self.statusBar().showMessage("Latest state reached, cannot Redo further!", 3000)
            return
        if not hasattr(self, 'undo_stack'): self.undo_stack = []
        
        self.undo_stack.append(str(self.soup))
        self.soup = self.parse_html(self.redo_stack.pop())
        self.refresh_tree(); self.update_preview()
        self.statusBar().showMessage("⏩ Redo successful!", 3000)

    def parse_html(self, content):
        try: return BeautifulSoup(content, 'lxml')
        except: return BeautifulSoup(content, 'html.parser')

    def check_and_save_if_dirty(self):
        if getattr(self, 'is_dirty', False):
            reply = QMessageBox.question(
                self,
                "Unsaved Changes Warning",
                "⚠️ The current project has UNSAVED CHANGES.\n\nDo you want to SAVE FILE before proceeding?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )
            if reply == QMessageBox.StandardButton.Save:
                self.save_file()
                return True
            elif reply == QMessageBox.StandardButton.Discard:
                return True
            else:
                return False
        return True

    def load_file_dialog(self):
        if not self.check_and_save_if_dirty():
            return

        if hasattr(self, 'view_stack'):
            self.view_stack.setCurrentIndex(0)

        p, _ = QFileDialog.getOpenFileName(self, "Open HTML File", BASE_DIR, "HTML (*.html *.htm)")
        if p:
            if not os.path.exists(p):
                QMessageBox.warning(self, "Invalid File Warning", f"This file does not exist on disk!\nIt may have been deleted or is an invalid Explorer reference.\nPath: {p}")
                return
                
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                    self.soup = self.parse_html(f.read())

                for s in self.soup.find_all('script'):
                    if not s.has_attr('src') and not s.has_attr('id') and s.string and "EDITOR_SCROLL" in s.string:
                        s.decompose()

                self.current_file_path = os.path.abspath(p)

                if hasattr(self, 'undo_stack'): self.undo_stack.clear()
                if hasattr(self, 'redo_stack'): self.redo_stack.clear()
                
                self.is_dirty = False
                self.lbl_current_file.setText(f"Viewing: <b>{os.path.basename(p)}</b>")
                self.refresh_tree(); self.update_preview()
            except Exception as e:
                QMessageBox.critical(self, "File Open Error", f"Unable to read file:\n{str(e)}")

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

        self.inp_text.page().runJavaScript("if(window.editor) { window.editor.setValue('<!-- Select a tag to view HTML code -->'); }")
        
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
        is_f = tag.name == 'form'

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
            js = f"""
            (function() {{
                var sel = window.getSelection();
                var ranges = [];
                if (sel && sel.rangeCount > 0) {{
                    for(var i=0; i<sel.rangeCount; i++) ranges.push(sel.getRangeAt(i));
                }}
                
                document.querySelectorAll('.editor-highlight').forEach(e => e.classList.remove('editor-highlight')); 
                var el = document.querySelector('[data-editor-id="{eid}"]'); 
                if(el) {{ el.classList.add('editor-highlight'); }}
                
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
                    
                    style_dict['max-width'] = '100%'
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
            
            self.statusBar().showMessage("🔒 New dimensions applied! Adjacent elements scaled automatically.", 5000)

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
            if (window.lastSelectionRange) {{
                var sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(window.lastSelectionRange);
            }}
            var node = window.getSelection().anchorNode;
            if (node) {{
                var el = node.nodeType === 3 ? node.parentNode : node;
                var ce = el.closest('[data-editor-id]');
                if (ce) ce.setAttribute('contenteditable', 'true');
            }}
            document.execCommand('{cmd}', false{val_str});
        }})();
        """
        self.web_view.page().runJavaScript(js, 0, lambda r: self.sync_from_preview())
        self.statusBar().showMessage(f"📝 Applied text format ({cmd})!", 3000)

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
        self.statusBar().showMessage(f"📏 Changed element font size to {new_size}px", 3000)

    def change_font_family(self, t):
        from PySide6.QtWidgets import QFontDialog
        ok, font = QFontDialog.getFont(self)
        if ok and font:
            self.save_state_for_undo()
            font_name = font.family()
            st = str(t.get('style', '')).strip()
            import re

            if 'font-family:' in st.lower():
                new_st = re.sub(r'font-family:\s*[^;]+;?', f"font-family: '{font_name}', sans-serif;", st, flags=re.IGNORECASE)
            else:
                new_st = st.strip(';') + ("; " if st else "") + f"font-family: '{font_name}', sans-serif;"
                
            t['style'] = new_st.strip('; ')
            
            item = self.tree.currentItem()
            if item: self.on_item_clicked(item, 0)
            self.apply_changes()
            self.statusBar().showMessage(f"🔤 Applied new Font Family: {font_name}", 4000)

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
        self.statusBar().showMessage(f"Text align: {align}", 3000)

    def insert_quick_html(self, t, html_str):
        self.save_state_for_undo()
        new_soup = self.parse_html(html_str)
        nodes = list((new_soup.body or new_soup).children)
        for n in nodes:
            if n.name: t.append(n)
                
        self.refresh_tree()
        self.update_preview()
        self.statusBar().showMessage("➕ Added new text block!", 3000)

    def insert_floating_textbox(self, t):
        html = '''<div style="position: relative; padding: 15px; margin: 10px 0; background: rgba(255,255,255,0.05); border: none; color: inherit; resize: both; overflow: auto; min-height: 100px; min-width: 150px; border-radius: 8px;">
            <h3 style="margin-top:0; color:#007acc;">Box Title</h3>
            <p>Enter free-form text content here. Use the handle at the bottom right corner to resize this box!</p>
        </div>'''
        self.insert_quick_html(t, html)

    def toggle_border(self, item, t):
        self.save_state_for_undo()
        st = str(t.get('style', ''))
        import re
        
        if st and not st.endswith(';'): st += ';'
        
        if 'border:' in st and 'none' not in st:
            st = re.sub(r'border:[^;]+;', 'border: none;', st)
            msg = "🚫 Turned border OFF!"
        elif 'border: none' in st:
            st = st.replace('border: none;', 'border: 2px dashed #007acc;')
            msg = "🔲 Turned border ON!"
        else:
            st += " border: 2px dashed #007acc;"
            msg = "🔲 Turned border ON!"
            
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
        self.is_dirty = True
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
                        setTimeout(() => newEl.classList.add('editor-highlight'), 50);
                    }}
                }}
            }})();
            """
            self.web_view.page().runJavaScript(js)
            self.statusBar().showMessage("✅ Changes updated (Seamless inline update without reload)!", 3000)
        else:
            self.update_preview()
            self.statusBar().showMessage("✅ Full page reloaded!", 3000)

    def make_html_mobile_responsive(self, soup_obj):
        """Clean-Sweep Engine: Removes legacy noise & injects Mobile Responsive CSS/JS v11.0"""
        if not soup_obj: return
        
        head = soup_obj.find('head')
        if not head:
            head = soup_obj.new_tag('head')
            if soup_obj.html: soup_obj.html.insert(0, head)

        for old_meta in soup_obj.find_all('meta', attrs={'name': 'viewport'}):
            old_meta.decompose()
        meta_vp = soup_obj.new_tag('meta', attrs={'name': 'viewport', 'content': 'width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes'})
        head.insert(0, meta_vp)

        garbage_ids = [
            'miniapp-base-css', 'universal-mobile-reset', 'universal-mobile-reset-css',
            'mobile-responsive-css', 'universal-mobile-engine-js', 'magic-mobile-runtime',
            'miniapp-nav-script', 'clean-mobile-engine-css', 'clean-spa-nav-js'
        ]
        for g_id in garbage_ids:
            old_el = soup_obj.find(id=g_id)
            if old_el: old_el.decompose()
        resp_style = soup_obj.new_tag('style', id='clean-mobile-engine-css')
        resp_style.string = """
* { box-sizing: border-box !important; }
img, video, iframe, embed, object, svg { max-width: 100% !important; height: auto !important; object-fit: contain; }
html, body { overflow-x: hidden !important; width: 100% !important; max-width: 100% !important; margin: 0 !important; padding: 0 !important; }

@media screen and (max-width: 768px) {
    body {
        display: flex !important;
        flex-direction: column !important;
        min-height: auto !important;
        overflow-y: auto !important;
    }
    
    aside, .thanh-dieu-huong, [class*="dieu-huong"], [class*="sidebar"] {
        position: relative !important;
        left: auto !important; top: auto !important; right: auto !important; bottom: auto !important;
        width: 100% !important;
        max-width: 100% !important;
        height: auto !important;
        max-height: none !important;
        margin: 0 !important;
        padding: 20px 15px !important;
        z-index: 10 !important;
        border-right: none !important;
        border-bottom: 2px solid #2a3441 !important;
        box-shadow: none !important;
        overflow: visible !important;
    }

    main, .vung-noi-dung-chinh, [class*="noi-dung-chinh"], [class*="main-content"] {
        position: relative !important;
        left: auto !important; top: auto !important; right: auto !important; bottom: auto !important;
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 !important;
        padding: 25px 15px !important;
        z-index: 1 !important;
        display: block !important;
        overflow: visible !important;
    }

    .trang-noi-dung { display: none !important; }
    .trang-noi-dung.hien-thi,
    .trang-noi-dung.trang-dang-hien-thi,
    .trang-noi-dung[style*="display: block"],
    .trang-noi-dung[style*="display:block"] {
        display: block !important;
        width: 100% !important;
    }

    .dashboard-layout, .row-wrap, .grid-wrap, .card-wrap, .luoi-noi-dung,
    [class*="header-box"], [class*="content-box"], [class*="app-content"],
    [class*="khung-app"], [class*="goi-giong"], [class*="chia-"],
    [style*="display: flex"], [style*="display:flex"],
    [style*="display: grid"], [style*="display:grid"] {
        display: flex !important;
        flex-direction: column !important;
        flex-wrap: wrap !important;
        width: 100% !important;
        max-width: 100% !important;
        height: auto !important;
        min-height: 0 !important;
        gap: 15px !important;
    }

    .app-media, .app-article, .app-header-text, .app-header-logo,
    .the-ung-dung, .card, .col, [class*="grid-item"],
    [class*="header-box"] > *, [class*="content-box"] > *,
    .luoi-noi-dung > *, .card-wrap > * {
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
        flex: none !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
    }

    .app-header-logo, .vung-logo {
        margin: 10px auto !important;
        align-self: center !important;
    }

    a:not(.card *), button, li, span, label, input, select, textarea, .menu-con, .mui-ten,
    .pagination, .pagination *, .nut-phan-trang, .nav-phan-trang, .nut-bam, .nut-menu {
        min-width: 0 !important;
        max-width: 100% !important;
    }
    a.nut-chuyen-trang, a[class*="nut-menu"], .nut-mo-menu-con, .tieu-de-muc-lon {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: space-between !important;
        width: 100% !important;
    }

    table {
        display: block !important;
        width: 100% !important;
        overflow-x: auto !important;
        white-space: nowrap !important;
        -webkit-overflow-scrolling: touch;
    }
    p, h1, h2, h3, h4, h5, h6, span, a, li, td, th {
        word-break: normal !important;
        overflow-wrap: break-word !important;
        white-space: normal !important;
    }
}
"""
        head.append(resp_style)

        nav_js = soup_obj.new_tag('script', id='clean-spa-nav-js')
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
                document.querySelectorAll('.trang-noi-dung').forEach(function(p) {
                    p.classList.remove('hien-thi', 'trang-dang-hien-thi');
                    p.style.setProperty('display', 'none', 'important');
                });
                targetPage.classList.add('hien-thi', 'trang-dang-hien-thi');
                targetPage.style.setProperty('display', 'block', 'important');
                document.querySelectorAll('[data-trang]').forEach(function(b) {
                    b.classList.remove('dang-chon', 'menu-dang-chon');
                });
                document.querySelectorAll('[data-trang="' + targetId + '"]').forEach(function(ab) {
                    ab.classList.add('dang-chon', 'menu-dang-chon');
                });
                window.scrollTo({ top: 0, behavior: 'instant' });
            }
        }
    });
});
"""
        if soup_obj.body:
            soup_obj.body.append(nav_js)

    def check_and_warn_legacy_template(self, soup_obj):
        if not soup_obj or getattr(self, '_legacy_warned', False):
            return
            
        legacy_keywords = [
            'skel.min.js', 'skel.js', 'skel-layers', 'skel-viewport',
            'jquery.scrollex', 'jquery.scrolly', 'jquery.dropotron', 'breakpoints.min.js'
        ]
        
        is_legacy = False
        for s in soup_obj.find_all('script'):
            src = str(s.get('src', '')).lower()
            content = str(s.string or '').lower()
            if any(k in src for k in legacy_keywords) or any(k in content for k in ['skel.', '.scrollex', '.scrolly']):
                is_legacy = True
                break
                
        if is_legacy:
            self._legacy_warned = True
            QMessageBox.warning(
                self,
                "⚠️ Outdated HTML Template Warning",
                "This HTML template uses outdated JavaScript libraries (Skel.js / jQuery Scrollex...)\n\n"
                "• These frameworks conflict with modern Chromium standards (Passive Event Listeners) and can cause scrolling freezes or glitches.\n"
                "• The tool still allows you to view the layout and edit Text/CSS, but dynamic scrolling animations may not work properly.\n\n"
                "👉 RECOMMENDATION: Select an HTML5 / Modern CSS template from the Library for the best experience!"
            )

    def unlock_legacy_preloader(self, soup_obj):
        if not soup_obj: return
        body = soup_obj.find('body')
        if body and body.get('class'):
            classes = body.get('class')
            if isinstance(classes, str): classes = classes.split()
            clean_classes = [c for c in classes if c not in ['is-preload', 'is-loading', 'is-resizing', 'is-preload-0', 'is-preload-1']]
            if clean_classes: body['class'] = clean_classes
            else: del body['class']

        head = soup_obj.find('head')
        if not head:
            head = soup_obj.new_tag('head')
            if soup_obj.html: soup_obj.html.insert(0, head)

        css_id = "universal-template-force-show-css"
        if not soup_obj.find(id=css_id):
            force_show_css = soup_obj.new_tag('style', id=css_id)
            force_show_css.string = """
            html, body {
                overflow-y: auto !important;
                overflow-x: hidden !important;
                height: auto !important;
                min-height: 100% !important;
                position: relative !important;
                opacity: 1 !important;
                visibility: visible !important;
            }
            #preloader, #loader, .preloader, .spinner, [class*="preloader"] {
                display: none !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }
            body > * { pointer-events: auto !important; }
            """
            head.append(force_show_css)

    def update_preview(self):
        if not self.soup: return

        self.check_and_warn_legacy_template(self.soup)

        self.unlock_legacy_preloader(self.soup)
        self.make_html_mobile_responsive(self.soup)
        
        html = str(self.soup)
        edit_mode_str = 'true' if getattr(self, 'is_edit_mode', True) else 'false'

        js = f"""
        <style id="mini-app-editor-style">
            * {{ box-sizing: border-box !important; }}
            .editor-highlight {{ outline: 3px solid #007acc !important; box-shadow: inset 0 0 15px rgba(0,122,204,0.4) !important; transition: outline 0.2s, box-shadow 0.2s; }}
            .editor-hover {{ outline: 2px dashed #ff9800 !important; cursor: pointer !important; transition: outline 0.1s; }}
            [contenteditable="true"] {{ outline: 2px dashed #4CAF50 !important; cursor: text !important; }}
            body.is-edit-mode img, body.is-edit-mode a {{ -webkit-user-drag: none !important; user-drag: none !important; }}
            body.is-edit-mode * {{ -webkit-user-select: none !important; user-select: none !important; }}
            body.is-edit-mode [contenteditable="true"], body.is-edit-mode [contenteditable="true"] * {{ -webkit-user-select: text !important; user-select: text !important; cursor: text !important; }}
        </style>
        <script id="mini-app-editor-script">
            window.lastClickTarget = null;
            window.currentEditingEl = null;
            window.lastSelectionRange = null; 
            window.isEditMode = {edit_mode_str};
            
            setInterval(function() {{
                if(window.isEditMode) document.body.classList.add('is-edit-mode');
                else document.body.classList.remove('is-edit-mode');
            }}, 200);

            document.addEventListener('dragstart', function(e) {{
                if(window.isEditMode && (!e.target.classList || !e.target.classList.contains('free-floating-element'))) {{
                    e.preventDefault();
                }}
            }}, true);

            let lastWidth = "", lastHeight = "";
            let activeDragEl = null;
            let startMouseX = 0, startMouseY = 0;
            let startElLeft = 0, startElTop = 0;

            document.addEventListener('mousedown', function(e) {{ 
                if(!window.isEditMode) return; 
                window.focus(); 
                var t = e.target;
                if(t.classList && t.classList.contains('free-floating-element')) {{
                    activeDragEl = t;
                    startMouseX = e.clientX; startMouseY = e.clientY;
                    startElLeft = parseFloat(window.getComputedStyle(t).left) || 0;
                    startElTop = parseFloat(window.getComputedStyle(t).top) || 0;
                    e.preventDefault(); return;
                }}
                var hl = document.querySelector('.editor-highlight'); 
                if (hl) {{ lastWidth = hl.style.width; lastHeight = hl.style.height; }} 
            }}, true);
            
            document.addEventListener('mousemove', function(e) {{
                if(!window.isEditMode) return;
                if (activeDragEl) {{
                    var dx = e.clientX - startMouseX; var dy = e.clientY - startMouseY;
                    activeDragEl.style.left = (startElLeft + dx) + 'px';
                    activeDragEl.style.top = (startElTop + dy) + 'px';
                }}
            }}, true);

            document.addEventListener('mouseup', function(e) {{
                if(!window.isEditMode) return;
                if (activeDragEl) {{
                    var eid = activeDragEl.getAttribute('data-editor-id');
                    if(eid) console.log("EDITOR_DRAG_POS:" + eid + "|" + activeDragEl.style.left + "|" + activeDragEl.style.top);
                    activeDragEl = null; return;
                }}
                var hl = document.querySelector('.editor-highlight');
                if (hl) {{
                    var w = hl.style.width; var h = hl.style.height;
                    if (w !== lastWidth || h !== lastHeight) {{
                        var eid = hl.getAttribute('data-editor-id');
                        if(eid) console.log("EDITOR_RESIZE:" + eid + "|" + w + "|" + h);
                        lastWidth = w; lastHeight = h;
                    }}
                }}
            }}, true);

            document.addEventListener('mouseover', function(e) {{
                if(!window.isEditMode || activeDragEl) return;
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
                console.log("EDITOR_HINT:🚫 Form Submit is disabled in Edit Mode.");
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
                            console.log("EDITOR_HINT:💡 In Edit Mode, page navigation is blocked!");
                        }}
                    }}
                }}
                var t = e.target;
                if (window.currentEditingEl && window.currentEditingEl.contains(t)) return; 
                if (window.currentEditingEl) {{
                    window.currentEditingEl.removeAttribute('contenteditable');
                    window.currentEditingEl = null;
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
                    e.preventDefault(); e.stopPropagation(); 
                    t.setAttribute('contenteditable', 'true');
                    t.focus();
                    window.currentEditingEl = t;
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

        base_dir = None
        if getattr(self, 'current_file_path', None) and os.path.exists(self.current_file_path):
            base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
        elif getattr(self, 'current_base_dir', None) and os.path.exists(self.current_base_dir):
            base_dir = self.current_base_dir
        else:
            base_dir = BASE_DIR
            
        base_url = QUrl.fromLocalFile(os.path.join(base_dir, "index.html"))
        self.web_view.setHtml(html, base_url)

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
        self.statusBar().showMessage("🔄 Syncing and preparing to save as new file...", 2000)
        self.web_view.page().runJavaScript("document.documentElement.outerHTML", 0, self._callback_save_as)

    def execute_save(self, filepath):
        if not filepath: return
        try:
            filepath = os.path.abspath(filepath)
            cl_soup = self.parse_html(str(self.soup))

            self.make_html_mobile_responsive(cl_soup)
            
            for t in cl_soup.find_all(True):
                if 'data-editor-id' in t.attrs: del t['data-editor-id']
                if 'data-locked' in t.attrs: del t['data-locked']
                if 'class' in t.attrs and 'editor-highlight' in t['class']:
                    t['class'].remove('editor-highlight')
                    if not t['class']: del t['class']
            
            old_nav = cl_soup.find(id='miniapp-nav-script')
            if old_nav: old_nav.decompose()
            
            nav_js = cl_soup.new_tag('script', id='miniapp-nav-script')
            nav_js.string = "document.addEventListener('DOMContentLoaded',function(){var pageIds=[];document.querySelectorAll('[data-trang]').forEach(function(btn){var tId=btn.getAttribute('data-trang');if(tId&&pageIds.indexOf(tId)===-1)pageIds.push(tId);});document.body.addEventListener('click',function(e){var btn=e.target.closest('[data-trang]');if(btn){var targetId=btn.getAttribute('data-trang');var targetPage=document.getElementById(targetId);if(targetPage){e.preventDefault();pageIds.forEach(function(id){var p=document.getElementById(id);if(p){p.classList.remove('trang-dang-hien-thi');p.style.setProperty('display','none','important');}});targetPage.classList.add('trang-dang-hien-thi');targetPage.style.setProperty('display','block','important');document.querySelectorAll('[data-trang]').forEach(function(b){b.classList.remove('menu-dang-chon');});document.querySelectorAll('[data-trang=\"'+targetId+'\"]').forEach(function(ab){ab.classList.add('menu-dang-chon');});}}});});"
            if cl_soup.body: cl_soup.body.append(nav_js)
            
            with open(filepath, 'w', encoding='utf-8') as f: 
                f.write(cl_soup.prettify())
            
            self.is_dirty = False
            self.statusBar().showMessage(f"💾 Saved and optimized for mobile responsive: {os.path.basename(filepath)}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Save File Error", f"Error:\n{str(e)}")

    def execute_save_as(self):
        default_dir = os.path.dirname(self.current_file_path) if self.current_file_path else BASE_DIR
        path, _ = QFileDialog.getSaveFileName(self, "Save As New File", default_dir, "HTML (*.html *.htm)")
        
        if path:
            if not path.lower().endswith('.html') and not path.lower().endswith('.htm'):
                path += '.html'
                
            self.current_file_path = os.path.abspath(path)
            self.lbl_current_file.setText(f"Viewing: <b>{os.path.basename(self.current_file_path)}</b>")
            self.execute_save(self.current_file_path)
            self.is_dirty = False

    def create_blank_page(self, theme="light"):
        if not self.check_and_save_if_dirty():
            return

        self.save_state_for_undo()

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
            self.current_file_path = None 
            self.is_dirty = True
            
            self.lbl_current_file.setText(f"Viewing: <b>Unsaved (Blank {theme.upper()} Page)</b>")
            self.soup = self.parse_html(blank_html)
            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage(f"📄 Created a blank {theme.upper()} page in memory! (Press Ctrl+S to save to file)", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Page Creation Error", f"Cannot create page:\n{str(e)}")

    def create_dashboard_page(self, theme="dark"):
        if not self.check_and_save_if_dirty():
            return

        self.save_state_for_undo()

        if theme == "dark":
            bg_body = "#0f111a"
            text_color = "#ffffff"
            sidebar_html = '<div class="sidebar" style="width: 250px; background: #161925; border-right: 1px solid #232736; display: flex; flex-direction: column; padding: 20px 0; flex-shrink: 0;"><div class="logo" style="text-align: center; margin-bottom: 30px;"><img src="https://via.placeholder.com/80" style="border-radius: 10px; margin-bottom: 10px;"><h2 style="margin: 0; color: #00d2ff; font-size: 20px;">MyApp</h2></div><div class="menu-group" style="padding: 0 20px; margin-bottom: 15px;"><div style="font-size: 12px; color: #666; margin-bottom: 10px; text-transform: uppercase;">Main Menu</div><a href="#" style="display: block; padding: 12px 15px; background: rgba(0,210,255,0.1); color: #00d2ff; border-radius: 8px; text-decoration: none; margin-bottom: 5px; border-left: 3px solid #00d2ff;">🚀 Overview</a><a href="#" style="display: block; padding: 12px 15px; color: #aaa; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">📁 Management</a><a href="#" style="display: block; padding: 12px 15px; color: #aaa; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">⚙️ Settings</a></div></div>'
            layout_style = "display: flex; min-height: 100vh; width: 100%; background: #0f111a; color: #fff; font-family: sans-serif;"
            main_style = "flex: 1; padding: 30px; display: flex; flex-direction: column; background: #0f111a; overflow-y: auto; overflow-x: hidden; width: 100%; box-sizing: border-box;"
        else:
            bg_body = "#f4f6f8"
            text_color = "#333333"
            sidebar_html = '<div class="sidebar" style="width: 250px; background: #ffffff; border-right: 1px solid #e0e0e0; display: flex; flex-direction: column; padding: 20px 0; flex-shrink: 0;"><div class="logo" style="text-align: center; margin-bottom: 30px;"><img src="https://via.placeholder.com/80" style="border-radius: 10px; margin-bottom: 10px;"><h2 style="margin: 0; color: #007acc; font-size: 20px;">MyApp</h2></div><div class="menu-group" style="padding: 0 20px; margin-bottom: 15px;"><div style="font-size: 12px; color: #888; margin-bottom: 10px; text-transform: uppercase;">Main Menu</div><a href="#" style="display: block; padding: 12px 15px; background: rgba(0,122,204,0.1); color: #007acc; border-radius: 8px; text-decoration: none; margin-bottom: 5px; border-left: 3px solid #007acc;">🚀 Overview</a><a href="#" style="display: block; padding: 12px 15px; color: #555; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">📁 Management</a><a href="#" style="display: block; padding: 12px 15px; color: #555; text-decoration: none; margin-bottom: 5px; transition: 0.3s;">⚙️ Settings</a></div></div>'
            layout_style = "display: flex; min-height: 100vh; width: 100%; background: #f4f6f8; color: #333; font-family: sans-serif;"
            main_style = "flex: 1; padding: 30px; display: flex; flex-direction: column; background: #f4f6f8; overflow-y: auto; overflow-x: hidden; width: 100%; box-sizing: border-box;"

        mobile_responsive_css = """
        <style id="mobile-responsive-css">
            @media (max-width: 768px) {
                .dashboard-layout { flex-direction: column !important; }
                .sidebar { width: 100% !important; border-right: none !important; border-bottom: 1px solid rgba(150,150,150,0.2) !important; padding-bottom: 10px !important; }
                .main-content { padding: 15px !important; }
                .row-wrap, .grid-wrap { flex-direction: column !important; display: flex !important; }
                .col, .card { width: 100% !important; max-width: 100% !important; flex: none !important; }
            }
        </style>
        """
        body = self.soup.find('body') if self.soup else None
        has_content = False
        if body:
            real_tags = [c for c in body.children if isinstance(c, Tag) and c.name not in ['script', 'style', 'link', 'meta']]
            if len(real_tags) > 0:
                has_content = True

        if has_content:
            if self.soup.find(class_='dashboard-layout') or self.soup.find(class_='sidebar'):
                QMessageBox.warning(self, "Notice", "The current page already contains a Sidebar/Dashboard structure!")
                return
                
            head = self.soup.find('head')
            if head and not self.soup.find(id='mobile-responsive-css'):
                head.append(self.parse_html(mobile_responsive_css).style)

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
                    continue
                main_node.append(child.extract())

            dashboard_node.append(sidebar_node)
            dashboard_node.append(main_node)
            body.append(dashboard_node)
            body['style'] = f"min-height: 100vh; margin: 0; padding: 0; font-family: sans-serif; background-color: {bg_body}; color: {text_color}; overflow-x: hidden;"

            self.is_dirty = True
            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage("🎛️ Wrapped content inside a Dashboard structure!", 5000)

        else:
            dashboard_html_full = f'<div class="dashboard-layout" style="{layout_style}">{sidebar_html}<div class="main-content" style="{main_style}"></div></div>'
            full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard {theme.capitalize()}</title>
    {mobile_responsive_css.strip()}
</head>
<body style="min-height: 100vh; margin: 0; padding: 0; font-family: sans-serif; background-color: {bg_body}; color: {text_color}; overflow-x: hidden;">
{dashboard_html_full}
</body>
</html>"""

            try:
                self.current_file_path = None
                self.is_dirty = True
                
                self.lbl_current_file.setText(f"Viewing: <b>Unsaved ({theme.capitalize()} Dashboard)</b>")
                self.soup = self.parse_html(full_html)
                self.refresh_tree()
                self.update_preview()
                self.statusBar().showMessage(f"🎛️ Created a Dashboard in memory! (Press Ctrl+S to save to file)", 5000)
            except Exception as e:
                QMessageBox.critical(self, "Page Creation Error", f"Cannot create page:\n{str(e)}")

    def export_project_to_zip(self):
        if not self.current_file_path:
            QMessageBox.warning(self, "Warning", "Please open or save the project as an HTML file before exporting to ZIP.")
            return

        zip_path, _ = QFileDialog.getSaveFileName(self, "Export Project to ZIP", os.path.dirname(self.current_file_path), "ZIP Archive (*.zip)")
        if not zip_path: return

        self.statusBar().showMessage("📦 Gathering resources and creating ZIP...", 2000)
        try:
            base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
            with tempfile.TemporaryDirectory() as temp_dir:
                assets_dir = os.path.join(temp_dir, "assets")
                os.makedirs(assets_dir, exist_ok=True)
                
                export_soup = self.parse_html(str(self.soup))
                self.make_html_mobile_responsive(export_soup)
                
                for t in export_soup.find_all(True):
                    if 'data-editor-id' in t.attrs: del t['data-editor-id']
                    if 'data-locked' in t.attrs: del t['data-locked']
                    if 'class' in t.attrs and 'editor-highlight' in t['class']:
                        t['class'].remove('editor-highlight')
                        if not t['class']: del t['class']
                
                for s_id in ["mini-app-editor-script", "mini-app-editor-style", "miniapp-nav-script"]:
                    s = export_soup.find(id=s_id)
                    if s: s.decompose()
                    
                nav_js = export_soup.new_tag('script', id='miniapp-nav-script')
                nav_js.string = "document.addEventListener('DOMContentLoaded',function(){var pageIds=[];document.querySelectorAll('[data-trang]').forEach(function(btn){var tId=btn.getAttribute('data-trang');if(tId&&pageIds.indexOf(tId)===-1)pageIds.push(tId);});document.body.addEventListener('click',function(e){var btn=e.target.closest('[data-trang]');if(btn){var targetId=btn.getAttribute('data-trang');var targetPage=document.getElementById(targetId);if(targetPage){e.preventDefault();pageIds.forEach(function(id){var p=document.getElementById(id);if(p){p.classList.remove('trang-dang-hien-thi');p.style.setProperty('display','none','important');}});targetPage.classList.add('trang-dang-hien-thi');targetPage.style.setProperty('display','block','important');document.querySelectorAll('[data-trang]').forEach(function(b){b.classList.remove('menu-dang-chon');});document.querySelectorAll('[data-trang=\"'+targetId+'\"]').forEach(function(ab){ab.classList.add('menu-dang-chon');});}}});});"
                if export_soup.body: export_soup.body.append(nav_js)

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
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(export_soup.prettify())
                    
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(html_path, arcname="index.html")
                    for root, _, files in os.walk(assets_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_name = os.path.join("assets", os.path.relpath(file_path, assets_dir)).replace('\\', '/')
                            zipf.write(file_path, arcname=arc_name)

            self.statusBar().showMessage(f"✅ ZIP export complete: {os.path.basename(zip_path)}", 5000)
            QMessageBox.information(self, "Export Successful", f"Project successfully exported and optimized for Mobile Responsive 100%!\n\nSaved at: {zip_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Error:\n{str(e)}")

    def export_production_zip(self):
        if not self.current_file_path:
            QMessageBox.warning(self, "Warning", "Please open or save the project as an HTML file before exporting to Production.")
            return

        zip_path, _ = QFileDialog.getSaveFileName(self, "Export Production (Extract Inline CSS & Optimize)", os.path.dirname(self.current_file_path), "ZIP Archive (*.zip)")
        if not zip_path: return

        self.statusBar().showMessage("🚀 Running Code Cleanup & Optimization Engine v11.0...", 2000)
        try:
            base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
            with tempfile.TemporaryDirectory() as temp_dir:
                assets_dir = os.path.join(temp_dir, "assets")
                css_dir = os.path.join(temp_dir, "css")
                os.makedirs(assets_dir, exist_ok=True)
                os.makedirs(css_dir, exist_ok=True)
                
                export_soup = self.parse_html(str(self.soup))
                self.make_html_mobile_responsive(export_soup)

                for t in export_soup.find_all(True):
                    if 'data-editor-id' in t.attrs: del t['data-editor-id']
                    if 'data-locked' in t.attrs: del t['data-locked']
                    if 'class' in t.attrs and 'editor-highlight' in t['class']:
                        t['class'].remove('editor-highlight')
                        if not t['class']: del t['class']

                for s_id in ["mini-app-editor-script", "mini-app-editor-style"]:
                    s = export_soup.find(id=s_id)
                    if s: s.decompose()
                    
                style_map = {}
                css_rules = [
                    "/* Optimized by Universal No-Code Designer v11.0 (Clean-Sweep) */",
                    "* { box-sizing: border-box !important; }",
                    "img, video, iframe, embed, object, svg { max-width: 100% !important; height: auto !important; object-fit: contain; }",
                    "html, body { overflow-x: hidden !important; width: 100% !important; max-width: 100% !important; margin: 0 !important; padding: 0 !important; }\n"
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

                css_rules.append("""
@media screen and (max-width: 768px) {
    body { display: flex !important; flex-direction: column !important; min-height: auto !important; overflow-y: auto !important; }
    aside, .thanh-dieu-huong, [class*="dieu-huong"], [class*="sidebar"] {
        position: relative !important; left: auto !important; top: auto !important; right: auto !important; bottom: auto !important;
        width: 100% !important; max-width: 100% !important; height: auto !important; max-height: none !important;
        margin: 0 !important; padding: 20px 15px !important; z-index: 10 !important; border-right: none !important;
        border-bottom: 2px solid #2a3441 !important; box-shadow: none !important; overflow: visible !important;
    }
    main, .vung-noi-dung-chinh, [class*="noi-dung-chinh"], [class*="main-content"] {
        position: relative !important; left: auto !important; top: auto !important; right: auto !important; bottom: auto !important;
        width: 100% !important; max-width: 100% !important; margin: 0 !important; padding: 25px 15px !important;
        z-index: 1 !important; display: block !important; overflow: visible !important;
    }
    .trang-noi-dung { display: none !important; }
    .trang-noi-dung.hien-thi, .trang-noi-dung.trang-dang-hien-thi, .trang-noi-dung[style*="display: block"], .trang-noi-dung[style*="display:block"] {
        display: block !important; width: 100% !important;
    }
    .dashboard-layout, .row-wrap, .grid-wrap, .card-wrap, .luoi-noi-dung,
    [class*="header-box"], [class*="content-box"], [class*="app-content"],
    [class*="khung-app"], [class*="goi-giong"], [class*="chia-"],
    [style*="display: flex"], [style*="display:flex"], [style*="display: grid"], [style*="display:grid"] {
        display: flex !important; flex-direction: column !important; flex-wrap: wrap !important;
        width: 100% !important; max-width: 100% !important; height: auto !important; min-height: 0 !important; gap: 15px !important;
    }
    .app-media, .app-article, .app-header-text, .app-header-logo,
    .the-ung-dung, .card, .col, [class*="grid-item"],
    [class*="header-box"] > *, [class*="content-box"] > *, .luoi-noi-dung > *, .card-wrap > * {
        width: 100% !important; max-width: 100% !important; min-width: 0 !important; flex: none !important; margin-left: 0 !important; margin-right: 0 !important;
    }
    .app-header-logo, .vung-logo { margin: 10px auto !important; align-self: center !important; }
    a:not(.card *), button, li, span, label, input, select, textarea, .menu-con, .mui-ten,
    .pagination, .pagination *, .nut-phan-trang, .nav-phan-trang, .nut-bam, .nut-menu {
        min-width: 0 !important; max-width: 100% !important;
    }
    a.nut-chuyen-trang, a[class*="nut-menu"], .nut-mo-menu-con, .tieu-de-muc-lon {
        display: flex !important; flex-direction: row !important; align-items: center !important; justify-content: space-between !important; width: 100% !important;
    }
    table { display: block !important; width: 100% !important; overflow-x: auto !important; white-space: nowrap !important; -webkit-overflow-scrolling: touch; }
    p, h1, h2, h3, h4, h5, h6, span, a, li, td, th { word-break: normal !important; overflow-wrap: break-word !important; white-space: normal !important; }
}""")

                prod_css_path = os.path.join(css_dir, "style.min.css")
                with open(prod_css_path, 'w', encoding='utf-8') as f:
                    f.write("\n".join(css_rules))
                
                head = export_soup.find('head')
                if not head:
                    head = export_soup.new_tag('head')
                    if export_soup.html: export_soup.html.insert(0, head)

                inline_mobile_css = export_soup.find(id='clean-mobile-engine-css')
                if inline_mobile_css: inline_mobile_css.decompose()
                
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
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(str(export_soup))
                    
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(html_path, arcname="index.html")
                    zipf.write(prod_css_path, arcname="css/style.min.css")
                    for root, _, files in os.walk(assets_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_name = os.path.join("assets", os.path.relpath(file_path, assets_dir)).replace('\\', '/')
                            zipf.write(file_path, arcname=arc_name)

            self.statusBar().showMessage(f"🚀 Production export complete: {os.path.basename(zip_path)}", 5000)
            QMessageBox.information(self, "Optimization Complete", f"Successfully cleaned up & optimized for Mobile Responsive v11.0 100%!\n\nSaved at: {zip_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Production export was interrupted:\n{str(e)}")
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
            "🔲 Left Heavy (1/3 - 2/3)": f'<div class="row-wrap" style="display:flex;flex-wrap:wrap;gap:15px;width:100%;"><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Left (1/3)</div><div class="col" style="flex:2 1 0%;min-width:250px;max-width:100%;{bz}">Right (2/3)</div></div>',
            "🔲 Right Heavy (2/3 - 1/3)": f'<div class="row-wrap" style="display:flex;flex-wrap:wrap;gap:15px;width:100%;"><div class="col" style="flex:2 1 0%;min-width:250px;max-width:100%;{bz}">Left (2/3)</div><div class="col" style="flex:1 1 0%;min-width:150px;max-width:100%;{bz}">Right (1/3)</div></div>'
        }
        fb_table = { "📊 Base Data Table": '<div style="overflow-x:auto;padding:10px;width:100%;"><table style="width:100%;border-collapse:collapse;margin:15px 0;font-family:sans-serif;color:inherit;"><tr style="background:#007acc;color:white;text-align:left;"><th style="padding:12px 15px;">ID</th><th style="padding:12px 15px;">Full Name</th><th style="padding:12px 15px;">Status</th></tr><tr style="border-bottom: 1px solid rgba(150,150,150,0.3);"><td style="padding:12px 15px;">#01</td><td style="padding:12px 15px;">John Doe</td><td style="padding:12px 15px;"><span style="background:#28a745;color:white;padding:4px 8px;border-radius:12px;font-size:12px;">Active</span></td></tr></table></div>' }
        fb_button = { "🔘 Button (Base Btn)": '<a href="#" style="display:inline-block;background:#007acc;color:#fff;padding:10px 25px;border-radius:25px;text-decoration:none;font-weight:bold;box-shadow:0 4px 6px rgba(0,122,204,0.3); transition: 0.3s;margin:5px;">Click Here</a>' }
        
        card_html = '<div class="card" style="flex:1 1 0%;min-width:200px;max-width:100%;display:flex;flex-direction:column;border:1px solid rgba(150,150,150,0.3);background:rgba(150,150,150,0.02);color:inherit;border-radius:10px;overflow:hidden;box-shadow: 0 4px 8px rgba(0,0,0,0.1);"><div style="height:150px;background:rgba(0,0,0,0.2);display:flex;align-items:center;justify-content:center;padding:10px;border-bottom:1px solid rgba(150,150,150,0.2);"><img src="https://via.placeholder.com/150" style="max-height:100%;max-width:100%;object-fit:contain;"></div><div style="padding:15px;display:flex;flex-direction:column;flex:1;"><h3 style="margin:0 0 10px 0;font-size:18px;">Card Title</h3><p style="font-size:14px;line-height:1.5;opacity:0.8;margin:0 0 15px 0;">Card description content.</p><a href="#" style="display:block;padding:10px;background:#007bff;color:white;text-decoration:none;border-radius:5px;text-align:center;margin-top:auto;font-weight:bold;">Details</a></div></div>'
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
                '<h3 style="margin:0 0 5px 0;font-size:18px;color:#fff;">John Smith</h3>'
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
                '<h3 style="margin:0 0 10px 0;color:#fff;font-size:18px;">Speed Optimized</h3>'
                '<p style="color:#aaa;font-size:14px;line-height:1.6;margin:0 0 20px 0;">The system is designed '
                'for ultrafast rendering, delivering a smooth experience for end users.</p>'
                '<a href="#" style="color:#ff007f;text-decoration:none;font-weight:bold;font-size:13px;">'
                'Explore Now ➔</a>'
            '</div>'
        )

        card_alert = (
            '<div style="display:flex;align-items:flex-start;gap:15px;background:rgba(255,193,7,0.1);'
            'border-left:4px solid #ffc107;padding:15px 20px;border-radius:0 8px 8px 0;margin:15px 0;width:100%;">'
                '<div style="font-size:24px;">🔔</div>'
                '<div>'
                    '<h4 style="margin:0 0 5px 0;color:#ffc107;font-size:16px;">Important Note</h4>'
                    '<p style="margin:0;color:#ddd;font-size:14px;line-height:1.5;">Please back up your data '
                    'before updating to avoid data loss.</p>'
                '</div>'
            '</div>'
        )

        fb_card = {
            "1 Single Card": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}</div>',
            "2 Horizontal Cards (1/2 - 1/2)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}{card_html}</div>',
            "3 Horizontal Cards (1/3 - 1/3 - 1/3)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}{card_html}{card_html}</div>',
            "2 Cards Asymmetric (Small 1/3 - Large 2/3)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_html}{card_large}</div>',
            "2 Cards Asymmetric (Large 2/3 - Small 1/3)": f'<div class="card-wrap" style="display:flex;gap:20px;flex-wrap:wrap;margin:15px 0;width:100%;">{card_large}{card_html}</div>',
            "🌟 Horizontal Media Card (Image Left - Text Right)": '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:20px;border:1px solid #333;background:rgba(255,255,255,0.03);padding:20px;border-radius:12px;width:100%;margin:15px 0;"><div style="flex:0 0 140px;height:120px;display:flex;align-items:center;justify-content:center;"><img src="https://via.placeholder.com/150" style="max-height:100%;max-width:100%;object-fit:contain;border-radius:10px;"></div><div style="flex:1 1 0%;min-width:200px;display:flex;flex-direction:column;"><h3 style="margin:0 0 10px 0;font-size:20px;color:#00d2ff;">App Tool Name</h3><p style="font-size:14px;line-height:1.6;color:#bbb;margin:0 0 15px 0;">Standard Media Object Card.</p><a href="#" style="align-self:flex-start;padding:10px 24px;background:#00bcd4;color:#fff;text-decoration:none;border-radius:8px;font-weight:bold;font-size:13px;">Download</a></div></div>',
            "📦 1 Large (Left) - 2 Small (Right)": card_1_large_2_small,
            "👤 User Profile Card": card_profile,
            "🚀 Feature Card": card_feature,
            "⚠️ Alert / Notification Card": card_alert
        }
        
        fb_header = { "Header (Base)": '<header style="background:inherit;color:inherit;padding:15px 30px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(150,150,150,0.3);width:100%;"><div style="font-size:24px;font-weight:bold;color:#007acc;">🚀 MyLogo</div><nav style="display:flex;gap:20px;"><a href="#" style="color:inherit;text-decoration:none;font-weight:500;">Home</a></nav></header>' }
        fb_footer = {
            "Template 1: Simple Centered": '<footer style="background:rgba(0,0,0,0.8);color:#fff;padding:30px 20px;text-align:center;margin-top:20px;width:100%;"><h3 style="margin-bottom:10px;">Connect With Us</h3><p style="margin-bottom:15px;font-size:14px;">Address: 123 Main Street, City</p></footer>',
            "Template 2: Multi-column & QR": '<footer style="background:rgba(0,0,0,0.85);color:#fff;padding:40px 20px;font-family:sans-serif;margin-top:20px;width:100%;"><div style="display:flex;flex-wrap:wrap;gap:30px;max-width:1000px;margin:0 auto;justify-content:space-between;"><div style="flex:1 1 0%;min-width:250px;max-width:100%;"><h3 style="color:#007acc;margin-top:0;">MyLogo</h3><p style="font-size:14px;color:#bbb;line-height:1.6;">Great solutions for everyone.</p></div><div style="flex:1 1 0%;min-width:150px;max-width:100%;text-align:center;"><h4 style="margin-top:0;">Scan QR</h4><img src="https://via.placeholder.com/100" style="width:100px;"></div></div></footer>'
        }

        fb_margin = {
            "📐 Standard Box Container (Max 1200px - Center)": '<div class="container-box" style="max-width:1200px; margin:0 auto; padding:0 15px; width:100%; box-sizing:border-box;"><div style="border:1px dashed #555; padding:20px; text-align:center; opacity:0.6;">1200px Container</div></div>',
            "📐 Article Container (Max 800px - Center)": '<div class="container-article" style="max-width:800px; margin:0 auto; padding:0 15px; width:100%; box-sizing:border-box;"><div style="border:1px dashed #555; padding:20px; text-align:center; opacity:0.6;">800px Container</div></div>',
            "📐 Left Indented Container": '<div class="container-left" style="margin-left:5%; padding-left:20px; border-left:3px solid #007acc; width:95%; box-sizing:border-box;"><div style="padding:10px; opacity:0.6;">Left Indented Container</div></div>',
            "📐 Full-width Fluid Container": '<div class="container-fluid" style="width:100%; padding:20px; box-sizing:border-box;"><div style="border:1px dashed #555; padding:20px; text-align:center; opacity:0.6;">Full-width Fluid Container</div></div>'
        }
        
        fb_divider = {
            "➖ Horizontal Rule (Solid)": '<hr style="border:none; border-top:2px solid rgba(150,150,150,0.5); margin:20px 0; width:100%;">',
            "➖ Horizontal Rule (Dashed/Light)": '<hr style="border:none; border-top:1px dashed rgba(150,150,150,0.3); margin:20px 0; width:100%;">',
            "📏 Spacer (20px)": '<div class="spacer" style="height:20px; width:100%; clear:both;"></div>',
            "📏 Spacer (50px)": '<div class="spacer" style="height:50px; width:100%; clear:both;"></div>'
        }

        fb_form = {
            "📝 Contact Form (Formspree Ready)": (
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
            "🔢 Pagination (Square Style) - Standalone": f'<div class="pagination-wrapper" style="width:100%; margin:20px 0; border: 1px dashed rgba(150,150,150,0.5); padding: 15px; border-radius: 8px; box-sizing: border-box;"><div id="sub-page-1" class="phan-trang-noi-dung" style="display:block; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#007acc;">Page 1 Content</h3><p style="opacity:0.7;">Drag and drop text, tables, images... here.</p></div><div id="sub-page-2" class="phan-trang-noi-dung" style="display:none; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#007acc;">Page 2 Content</h3><p style="opacity:0.7;">This is page 2.</p></div><div class="pagination" style="display:flex; justify-content:center; align-items:center; gap:8px; width:100%; font-family:sans-serif;"><a class="nav-phan-trang" data-action="first" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&laquo;</a><a class="nav-phan-trang" data-action="prev" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&lsaquo;</a><a class="nut-phan-trang" data-page="sub-page-1" data-active-bg="#007acc" data-disp="inline-block" onclick="{js_pag_switch}" style="padding:8px 15px; background:#007acc; color:#fff; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer; box-shadow:0 0 10px rgba(0,122,204,0.5); border: 1px solid rgba(150,150,150,0.3);">1</a><a class="nut-phan-trang" data-page="sub-page-2" data-active-bg="#007acc" data-disp="inline-block" onclick="{js_pag_switch}" style="padding:8px 15px; background:transparent; color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer; border: 1px solid rgba(150,150,150,0.3);">2</a><a class="nav-phan-trang" data-action="next" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&rsaquo;</a><a class="nav-phan-trang" data-action="last" onclick="{js_pag_switch}" style="padding:8px 12px; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:4px; font-weight:bold; cursor:pointer;">&raquo;</a></div></div>',
            
            "🔢 Pagination (Round Style) - Standalone": f'<div class="pagination-wrapper" style="width:100%; margin:20px 0; border: 1px dashed rgba(150,150,150,0.5); padding: 15px; border-radius: 8px; box-sizing: border-box;"><div id="sub-page-1-rnd" class="phan-trang-noi-dung" style="display:block; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#28a745;">Page 1 Content</h3><p style="opacity:0.7;">Drag and drop text, tables, images... here.</p></div><div id="sub-page-2-rnd" class="phan-trang-noi-dung" style="display:none; min-height:150px; width:100%; margin-bottom:20px;"><h3 style="margin-top:0; color:#28a745;">Page 2 Content</h3><p style="opacity:0.7;">This is page 2.</p></div><div class="pagination" style="display:flex; justify-content:center; align-items:center; gap:8px; width:100%; font-family:sans-serif;"><a class="nav-phan-trang" data-action="first" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&laquo;</a><a class="nav-phan-trang" data-action="prev" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&lsaquo;</a><a class="nut-phan-trang" data-page="sub-page-1-rnd" data-active-bg="#28a745" data-disp="flex" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:#28a745; color:#fff; text-decoration:none; border-radius:50%; font-weight:bold; box-shadow:0 0 10px rgba(40,167,69,0.5); cursor:pointer; border: 1px solid rgba(150,150,150,0.3);">1</a><a class="nut-phan-trang" data-page="sub-page-2-rnd" data-active-bg="#28a745" data-disp="flex" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer; border: 1px solid rgba(150,150,150,0.3);">2</a><a class="nav-phan-trang" data-action="next" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&rsaquo;</a><a class="nav-phan-trang" data-action="last" onclick="{js_pag_switch}" style="width:36px; height:36px; display:flex; align-items:center; justify-content:center; background:transparent; border:1px solid rgba(150,150,150,0.3); color:inherit; text-decoration:none; border-radius:50%; font-weight:bold; cursor:pointer;">&raquo;</a></div></div>'
        }

        row1.addWidget(create_dropdown_btn("🔲 Layout ▼", load_templates("layout.json", fb_layout)))
        row1.addWidget(create_dropdown_btn("📊 Table ▼", load_templates("table.json", fb_table)))
        row1.addWidget(create_dropdown_btn("🖼️ Card ▼", load_templates("card.json", fb_card)))
        
        row2.addWidget(create_dropdown_btn("🔝 Header ▼", load_templates("header.json", fb_header)))
        row2.addWidget(create_dropdown_btn("🔚 Footer ▼", load_templates("footer.json", fb_footer)))
        row2.addWidget(create_dropdown_btn("🔘 Button ▼", load_templates("button.json", fb_button)))

        row2.addWidget(create_dropdown_btn("📝 Form ▼", load_templates("form.json", fb_form)))
        row2.addWidget(create_dropdown_btn("🔢 Pagination ▼", load_templates("pagination.json", fb_nav)))

        btn_blank = QPushButton("📄 New Page ▼")
        btn_blank.setStyleSheet("background-color: #28a745; color: white; padding: 6px; border-radius: 4px; font-weight: bold;")
        menu_blank = QMenu(btn_blank)
        menu_blank.setStyleSheet("QMenu { background:#252526; color:white; border:1px solid #3e3e42; } QMenu::item { padding: 5px 20px; } QMenu::item:selected {background:#094771;}")
        menu_blank.addAction("🌞 Light Page (Light Mode)").triggered.connect(lambda: self.create_blank_page("light"))
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

        row3.addWidget(create_dropdown_btn("📐 Margin/Container ▼", load_templates("margin.json", fb_margin)))

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
                container_to_append = body

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
                            target.append(e)
                    else:
                        target.append(e)

            if e.name != 'style': last = e
            
        self.refresh_tree()
        self.update_preview()
        if last: self.select_tree_item_by_id(str(id(last)))

        if not t or t.name == 'body':
            self.statusBar().showMessage("➕ Located main design area and inserted element successfully!", 5000)
        else:
            self.statusBar().showMessage("➕ Inserted block into the currently selected container context!", 3000)

    def quick_replace_image(self, item, t):
        if getattr(self, 'current_file_path', None) and os.path.exists(self.current_file_path):
            base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
        elif getattr(self, 'current_base_dir', None) and os.path.exists(self.current_base_dir):
            base_dir = self.current_base_dir
        else:
            base_dir = BASE_DIR
            
        p, _ = QFileDialog.getOpenFileName(self, "Select New Image", base_dir, "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not p: return
        
        try:
            target_path = os.path.relpath(p, base_dir).replace('\\', '/')
        except ValueError:
            target_path = "file:///" + p.replace('\\', '/')
            
        self.save_state_for_undo()
        target_img = t
        is_bg_image = False
        st = str(t.get('style', '')).strip()
        import re
        
        if t.name not in ['img', 'picture', 'source', 'svg']:
            inner_img = t.find(['img', 'picture'])
            if inner_img:
                target_img = inner_img
            elif 'url(' in st.lower() or 'background' in st.lower():
                is_bg_image = True

        if is_bg_image:
            st = re.sub(r'url\([^\)]+\)', f"url('{target_path}')", st, flags=re.IGNORECASE)
            t['style'] = st.strip('; ')
        elif target_img.name == 'picture':
            for child in target_img.find_all(['source', 'img']):
                if 'loading' in child.attrs: del child['loading']
                if child.has_attr('srcset'): child['srcset'] = target_path
                if child.has_attr('src'): child['src'] = target_path
                if child.has_attr('data-src'): child['data-src'] = target_path
                if child.has_attr('data-srcset'): child['data-srcset'] = target_path
        else:
            for lazy_attr in ['loading', 'decoding']:
                if lazy_attr in target_img.attrs:
                    del target_img[lazy_attr]
            
            target_img['src'] = target_path
            for attr in ['srcset', 'data-src', 'data-lazy', 'data-lazy-src', 'data-original', 'data-srcset']:
                if target_img.has_attr(attr):
                    target_img[attr] = target_path
        if self.current_node == t or self.current_node == target_img:
            self.inp_src.setText(target_path)
            if is_bg_image:
                self.inp_style.setPlainText(t.get('style', '').replace('; ', ';\n'))
            
        self.refresh_tree()
        self.update_preview()

        eid = t.get('data-editor-id')
        if not eid and target_img != t:
            eid = target_img.get('data-editor-id')
            
        if eid:
            js = f"""
            (function(){{
                var el = document.querySelector('[data-editor-id="{eid}"]');
                if(!el) return;
                var newUrl = {json.dumps(target_path)};
                
                if ({'true' if is_bg_image else 'false'}) {{
                    el.style.backgroundImage = "url('" + newUrl + "')";
                    return;
                }}
                
                var img = (el.tagName === 'IMG') ? el : el.querySelector('img');
                if (img) {{
                    img.removeAttribute('loading');
                    img.removeAttribute('decoding');
                    img.setAttribute('src', newUrl);
                    img.src = newUrl;
                    if(img.hasAttribute('srcset')) img.setAttribute('srcset', newUrl);
                    if(img.hasAttribute('data-src')) img.setAttribute('data-src', newUrl);
                    if(img.hasAttribute('data-srcset')) img.setAttribute('data-srcset', newUrl);
                }}
                
                var pic = el.closest('picture') || (el.tagName === 'PICTURE' ? el : el.querySelector('picture'));
                if (pic) {{
                    pic.querySelectorAll('source, img').forEach(function(c){{
                        c.removeAttribute('loading');
                        if(c.hasAttribute('srcset')) c.setAttribute('srcset', newUrl);
                        if(c.hasAttribute('src')) {{
                            c.setAttribute('src', newUrl);
                            c.src = newUrl;
                        }}
                    }});
                }}
            }})();
            """
            self.web_view.page().runJavaScript(js)
            
        self.statusBar().showMessage(f"🖼️ Replaced image successfully: {os.path.basename(p)}", 4000)

    def replace_image_via_js(self):
        p = self.get_relative_path("Select Image", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not p: return
        self.save_state_for_undo()
        js = f"(function(){{ var t = window.lastContextTarget || window.lastClickTarget; if(!t) return 0; var img = (t.tagName==='IMG' || t.tagName==='PICTURE') ? t : t.querySelector('img'); if(img) {{ img.removeAttribute('loading'); img.setAttribute('src', {json.dumps(p)}); img.src = {json.dumps(p)}; if(img.hasAttribute('srcset')) img.setAttribute('srcset', {json.dumps(p)}); return 1; }} return 0; }})();"
        self.web_view.page().runJavaScript(js, 0, lambda r: self.sync_from_preview() if r==1 else QMessageBox.warning(self, "Error", "No image tag found in this area."))

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
            
            self.is_dirty = True
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
                if isinstance(old_id, list): old_id = old_id[0]
                if old_id not in id_map:
                    clean_id = old_id.split("_copy")[0] if "_copy" in old_id else old_id
                    id_map[old_id] = f"{clean_id}_copy{random.randint(100,999)}"
                t['id'] = id_map[old_id]
                
        return nt

    def kbd_adjust_font(self, delta):
        js = f"""
        (function() {{
            var target = window.currentEditingEl;
            
            if (!target) {{
                var sel = window.getSelection();
                if (sel.rangeCount > 0 && sel.toString().trim() !== "") {{
                    var node = sel.anchorNode;
                    target = node.nodeType === 3 ? node.parentNode : node;
                }}
            }}
            
            if (!target) target = document.querySelector('.editor-highlight');
            
            if (target) {{
                var ce = target.closest('[data-editor-id]');
                if (ce) {{
                    var currentSize = parseFloat(window.getComputedStyle(ce).fontSize) || 16;
                    var newSize = Math.max(8, currentSize + ({delta}));
                    ce.style.setProperty('font-size', newSize + 'px', 'important');
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

                st = str(t.get('style', ''))
                import re
                if 'font-size' in st:
                    new_st = re.sub(r'font-size:\s*[\d.]+px', f'font-size: {new_size}px', st)
                else:
                    new_st = st.strip(';') + ("; " if st else "") + f"font-size: {new_size}px;"
                
                t['style'] = new_st.strip('; ')

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

        style_str = str(t.get('style', '')).lower()
        is_bg_img = 'url(' in style_str and 'background' in style_str

        is_direct_img = t.name in ['img', 'picture', 'source', 'svg']
        is_small_wrapper_img = False
        if not is_direct_img and t.name in ['a', 'figure', 'span', 'div']:
            cls_str = " ".join(t.get('class', [])).lower()
            if not any(k in cls_str for k in ['row', 'col', 'container', 'grid', 'main', 'section', 'header', 'footer']):
                if len(t.find_all('img')) == 1:
                    is_small_wrapper_img = True
                    
        is_image_target = is_direct_img or is_small_wrapper_img or is_bg_img
        
        if is_image_target: 
            m.addAction("🖼️ Quick Replace Image (Fixes lazy-load & wrapper images)...").triggered.connect(lambda: self.quick_replace_image(item, t))
            if t.name == 'img' or (is_small_wrapper_img and t.name not in ['body', 'html']):
                m.addAction("🔄 Image Fit Mode (Cover / Contain)").triggered.connect(lambda: self.toggle_image_fit(item, t))
            m.addSeparator()
            
        if len([c for c in t.children if isinstance(c, Tag)]) > 1: m.addAction("🔄 Reverse Children Order").triggered.connect(lambda: self.reverse_children(item, t)); m.addSeparator()

        if t.name not in ['body', 'html'] or t.name in ['div', 'section', 'header', 'footer', 'main', 'article', 'aside', 'body']:
            m_img = m.addMenu("🖼️ Insert & Manage Image (Resizable)...")
            
            if t.name not in ['body', 'html']:
                m_img_in = m_img.addMenu("📥 Insert INSIDE this block (Text wrapped)")
                m_img_in.addAction("⬅️ Align Left").triggered.connect(lambda: self.insert_new_image_inside(item, t, "left"))
                m_img_in.addAction("➡️ Align Right").triggered.connect(lambda: self.insert_new_image_inside(item, t, "right"))
                m_img_in.addAction("⬆️ Align Top").triggered.connect(lambda: self.insert_new_image_inside(item, t, "top"))
                m_img_in.addAction("⬇️ Align Bottom").triggered.connect(lambda: self.insert_new_image_inside(item, t, "bottom"))
                
                m_img_out = m_img.addMenu("➕ Insert OUTSIDE this block (Standalone)")
                m_img_out.addAction("⬅️ Insert Left (Split column)").triggered.connect(lambda: self.insert_new_image_relative(item, t, "left"))
                m_img_out.addAction("➡️ Insert Right (Split column)").triggered.connect(lambda: self.insert_new_image_relative(item, t, "right"))
                m_img_out.addAction("⬆️ Insert Above").triggered.connect(lambda: self.insert_new_image_relative(item, t, "above"))
                m_img_out.addAction("⬇️ Insert Below").triggered.connect(lambda: self.insert_new_image_relative(item, t, "below"))
                m_img.addSeparator()

            if t.name in ['div', 'section', 'header', 'footer', 'main', 'article', 'aside', 'body']:
                m_img.addAction("🌄 Set as Background Image...").triggered.connect(lambda: self.set_background_image(item, t))

            if 'image-wrapper-free' in t.get('class', []) or (t.parent and 'image-wrapper-free' in t.parent.get('class', [])):
                m_img.addSeparator()
                m_img.addAction("🔒 Lock Image Frame (Disable resize handle)").triggered.connect(lambda: self.lock_floating_image(item, t))
                
            m.addSeparator()

        if t.name not in ['body', 'html', 'img']:
            m.addAction("📐 Toggle Free Resizing (Resize Handle)...").triggered.connect(lambda: self.toggle_resize_block(item, t))
            m.addSeparator()

        m.addAction("🎨 Change Block Background Color...").triggered.connect(lambda: self.quick_change_bg_color(item, t))
        m.addAction("✨ Add Hover Effect...").triggered.connect(lambda: self.add_hover_effect(item, t))
        m.addAction("🔲 Toggle Border...").triggered.connect(lambda: self.toggle_border(item, t))

        m_text = m.addMenu("📝 Text Formatting & Editing...")
        m_text.addAction("✂️ Cut").triggered.connect(lambda: self.web_view.page().triggerAction(QWebEnginePage.WebAction.Cut))
        m_text.addAction("📋 Copy").triggered.connect(lambda: self.web_view.page().triggerAction(QWebEnginePage.WebAction.Copy))
        m_text.addAction("📌 Paste").triggered.connect(lambda: self.web_view.page().triggerAction(QWebEnginePage.WebAction.Paste))
        m_text.addSeparator()
        m_text.addAction("𝐁 Bold Selected Text (Ctrl+B)").triggered.connect(lambda: self.exec_text_cmd('bold'))
        m_text.addAction("𝐼 Italicize Selected Text (Ctrl+I)").triggered.connect(lambda: self.exec_text_cmd('italic'))
        m_text.addAction("̲U Underline Selected Text (Ctrl+U)").triggered.connect(lambda: self.exec_text_cmd('underline'))
        m_text.addAction("🎨 Color Selected Text...").triggered.connect(self.change_selected_text_color)

        m_text.addAction("🔤 Change Font Family...").triggered.connect(lambda: self.change_font_family(t))
        m_text.addSeparator()
        
        m_text.addAction("➕ Increase Font Size (+2px)").triggered.connect(lambda: self.change_font_size(t, 2))
        m_text.addAction("➖ Decrease Font Size (-2px)").triggered.connect(lambda: self.change_font_size(t, -2))
        m_text.addSeparator()
        m_text.addAction("⬅️ Align Left").triggered.connect(lambda: self.change_text_align(t, 'left'))
        m_text.addAction("↔️ Center Align").triggered.connect(lambda: self.change_text_align(t, 'center'))
        m_text.addAction("➡️ Align Right").triggered.connect(lambda: self.change_text_align(t, 'right'))

        if t.name not in ['body', 'html', 'img', 'input', 'br', 'hr']:
            m_add_text = m.addMenu("➕ Insert Text Box / Heading...")
            m_add_text.addAction("🔲 Free Floating Text Box (Resizable)").triggered.connect(lambda: self.insert_floating_textbox(t))
            m_add_text.addAction("🏷️ Heading 1 (H1)").triggered.connect(lambda: self.insert_quick_html(t, '<h1 style="color:#007acc; margin-bottom:10px;">New Heading</h1>'))
            m_add_text.addAction("💬 Paragraph (P)").triggered.connect(lambda: self.insert_quick_html(t, '<p style="line-height:1.6; opacity:0.8;">Enter your paragraph text here...</p>'))

            m_add_tbl = m.addMenu("📊 Insert Table (Multi-directional)...")
            m_add_tbl.addAction("⬅️ Insert Left (Split view)").triggered.connect(lambda: self.insert_component_relative(item, t, "left", "table"))
            m_add_tbl.addAction("➡️ Insert Right (Split view)").triggered.connect(lambda: self.insert_component_relative(item, t, "right", "table"))
            m_add_tbl.addAction("⬆️ Insert Above").triggered.connect(lambda: self.insert_component_relative(item, t, "above", "table"))
            m_add_tbl.addAction("⬇️ Insert Below").triggered.connect(lambda: self.insert_component_relative(item, t, "below", "table"))
            
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
            m.addAction("📄 ADD PAGINATION PAGE (New number + blank frame)").triggered.connect(lambda: self.add_pagination_page(pag_container))
            m.addSeparator()

        m_add_layer = m.addMenu("📦 Add Layer / Category...")
        m_add_layer.addAction("📌 Add Blank Layer (Sibling)").triggered.connect(lambda: self.add_blank_layer(item, t, "sibling"))
        m_add_layer.addAction("📥 Add Blank Layer (Child)").triggered.connect(lambda: self.add_blank_layer(item, t, "inside"))
        m_add_layer.addSeparator()
        m_add_layer.addAction("↳ Add Sub-menu Item to Menu").triggered.connect(lambda: self.add_sub_item(item, t))
        m_add_layer.addAction("➖ Add Sibling Category").triggered.connect(lambda: self.add_sibling_category(item, t))
        m_add_layer.addAction("🔽 Create Collapsible Content Block (Toggle on click)").triggered.connect(lambda: self.create_collapsible_content(item, t))
        m_add_layer.addAction("🔗 Create New Page & Link to Button").triggered.connect(lambda: self.create_linked_page(item, t))
        
        m_add_layer.addSeparator()
        m_add_layer.addAction("📄 Create Blank Tab Page (Link as content for this category)").triggered.connect(lambda: self.add_blank_page_to_menu(item, t))
        m_add_layer.addAction("🔢 Insert Internal Pagination (Inside block)").triggered.connect(lambda: self.insert_inner_pagination(item, t))
        
        m_add_layer.addSeparator()
        m_add_layer.addAction("🧲 Attach Safe Link / Download File...").triggered.connect(lambda: self.attach_safe_link(item, t))
        
        m.addSeparator()
        is_locked = t.get('data-locked') == 'true'
        if is_locked:
            m.addAction("🔓 UNLOCK Structure").triggered.connect(lambda: self.toggle_lock(item, t))
        else:
            m.addAction("🔒 LOCK Structure (Protect CSS)").triggered.connect(lambda: self.toggle_lock(item, t))
        m.addSeparator()

        m.addAction("📏 RESIZE TOOLS:").setEnabled(False)
        a_vert = m.addAction("   ↕️ Vertical Resize (Standalone)")
        a_horz = m.addAction("   ↔️ Horizontal Resize (Flex/Grid child)")
        a_diag = m.addAction("   ⤡ Diagonal Resize (Image/Video)")

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
        m.addAction("⚙️ Manual Dimension Settings...").triggered.connect(lambda: self.prepare_quick_resize(item, t))

        m.addAction("🛠️ Edit Raw HTML Code...").triggered.connect(lambda: self.edit_raw_html(item, t))
        
        m.addSeparator()

        if t.name not in ['body', 'html']:
            m.addAction("👯 Duplicate").triggered.connect(lambda: self.quick_duplicate(item, t))
            m.addAction("✂️ Cut HTML Element").triggered.connect(lambda: self.cut_element(item, t))
        m.addAction("📋 Copy HTML Element (Smart Macro)").triggered.connect(lambda: self.copy_element(item, t))
        
        p_in = m.addAction("📌 Paste INSIDE (Child)"); p_in.triggered.connect(lambda: self.paste_element(item, t, "inside"))
        p_sib = m.addAction("📌 Paste SIBLING"); p_sib.triggered.connect(lambda: self.paste_element(item, t, "sibling"))
        if t.name in ['body', 'html']: p_sib.setEnabled(False)
        if not self.clipboard_node: p_in.setEnabled(False); p_sib.setEnabled(False)

        m.addSeparator()
        if t.name not in ['body', 'html']: m.addAction("🗑️ DELETE").triggered.connect(lambda: self.delete_html_element(item, t))
        
        m.addSeparator()
        m.addAction("🔄 Sync Content from Preview").triggered.connect(self.sync_from_preview)
        
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
                var oldH = document.getElementById('magic-img-resizer');
                if(oldH) oldH.remove();

                var hnd = document.createElement('div');
                hnd.id = 'magic-img-resizer';
                hnd.innerHTML = '⤡';
                hnd.style.cssText = 'position:absolute; width:28px; height:28px; background:#e67e22; color:#fff; text-align:center; line-height:28px; cursor:nwse-resize; z-index:2147483647; border-radius:50%; font-size:15px; box-shadow:0 2px 6px rgba(0,0,0,0.5); font-weight:bold;';
                document.body.appendChild(hnd);

                function updateHndPos() {{
                    var rect = el.getBoundingClientRect();
                    hnd.style.left = (rect.right - 14 + window.scrollX) + 'px';
                    hnd.style.top = (rect.bottom - 14 + window.scrollY) + 'px';
                }}
                updateHndPos();

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
        
        msg = "✅ Orange resize handle ⤡ appeared at the corner!" if is_img else "✅ Resize icon appeared at the bottom-right corner!"
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
        dialog.setWindowTitle(f"📏 Adjust Dimensions: <{t.name}>")
        dialog.setStyleSheet("""
            QDialog { background-color: #252526; font-family: 'Segoe UI'; font-size: 13px; font-weight: bold; }
            QLabel { color: #ce9178; }
            QLineEdit, QComboBox { background-color: #1e1e1e; border: 1px solid #3e3e42; padding: 8px; color: #4fc1ff; border-radius: 4px; font-size: 14px;}
            QPushButton { background-color: #0e639c; color: white; padding: 10px; border-radius: 4px; border: none; font-size: 14px;}
            QPushButton:hover { background-color: #1177bb; }
            QCheckBox { color: #28a745; font-size: 13px; margin: 5px 0;}
        """)
        layout = QVBoxLayout(dialog)
        
        info_lbl = QLabel(f"💡 <b>Currently displayed: {real_w} x {real_h}</b><br><i style='color:#888;font-size:12px;'>(Tip for large blocks: Leave Height as 'auto' so it wraps content properly without clipping text)</i>")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)
        
        form = QFormLayout()
        form.setContentsMargins(0, 10, 0, 10)
        
        inp_w = QLineEdit(style_dict.get('width', '')); inp_w.setPlaceholderText(f"e.g., {real_w}, 100%, or auto")
        inp_h = QLineEdit(style_dict.get('height', '')); inp_h.setPlaceholderText("e.g., auto")

        inp_ov = QComboBox()
        inp_ov.addItems(["(Default) Free", "Auto scrollbar when overflowing (auto)", "Hide overflowing content (hidden)"])
        old_ov = style_dict.get('overflow', '')
        if old_ov == 'auto': inp_ov.setCurrentIndex(1)
        elif old_ov == 'hidden': inp_ov.setCurrentIndex(2)

        inp_flex = QComboBox()
        inp_flex.addItems([
            "(Default by original code)", 
            "Stack elements vertically (Column - Prevents overlap)", 
            "Arrange elements horizontally (Row)",
            "Center all content (Center)"
        ])
        old_display = style_dict.get('display', '')
        old_dir = style_dict.get('flex-direction', '')
        if old_display == 'flex' and old_dir == 'column': inp_flex.setCurrentIndex(1)
        elif old_display == 'flex' and old_dir == 'row': inp_flex.setCurrentIndex(2)
        elif old_display == 'flex': inp_flex.setCurrentIndex(3)

        form.addRow("Width:", inp_w)
        form.addRow("Height:", inp_h)
        form.addRow("Overflow behavior:", inp_ov)
        form.addRow("Child layout:", inp_flex)
        
        layout.addLayout(form)
        
        btn_apply = QPushButton("✔️ Apply Dimensions")
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
                style_dict['gap'] = '10px'
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
            self.statusBar().showMessage(f"📐 Refined structure for <{t.name}>!", 3000)
    
    def toggle_image_fit(self, item, t):
        self.save_state_for_undo()
        st = str(t.get('style', ''))
        if 'object-fit: cover' in st or 'object-fit:cover' in st:
            new_st = st.replace('object-fit: cover', 'object-fit: contain').replace('object-fit:cover', 'object-fit:contain')
            msg = "Switched to: 🖼️ FULL IMAGE DISPLAY (Contain)"
        else:
            if 'object-fit' in st:
                new_st = st.replace('object-fit: contain', 'object-fit: cover').replace('object-fit:contain', 'object-fit:cover')
            else:
                new_st = st + ("; object-fit: cover;" if st else "object-fit: cover;")
            msg = "Switched to: ✂️ FILL & CROP (Cover)"
        
        t['style'] = new_st
        self.on_item_clicked(item, 0)
        self.apply_changes()
        self.statusBar().showMessage(msg, 5000)
    
    def quick_change_bg_color(self, item, t):
        c = QColorDialog.getColor(QColor(), self, "Select Element Background Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
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
            self.statusBar().showMessage(f"🎨 Changed background color of <{t.name}>!", 3000)

    def convert_to_link(self):
        if not self.current_node: return
        self.save_state_for_undo()
        t = self.current_node
        
        parent_node = t.parent

        if t.name == 'button':
            t.name = 'a'
            t['href'] = '#'
            msg = "🪄 Converted Button to Link (a)!"
            target_node = t
            update_node = t

        else:
            new_a = self.soup.new_tag('a', href='#')
            new_a['style'] = "text-decoration: none; color: inherit; display: inline-block;"
            t.wrap(new_a)
            msg = f"🪄 Wrapped a Link around tag <{t.name}>!"
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

    def set_background_image(self, item, t):
        p, _ = QFileDialog.getOpenFileName(self, "Select Background Image", "", "Images (*.png *.jpg *.jpeg *.gif *.webp)")
        if not p: return

        base_dir = os.path.dirname(os.path.abspath(self.current_file_path)) if self.current_file_path else BASE_DIR
        try:
            target_path = os.path.relpath(p, base_dir).replace('\\', '/')
        except ValueError:
            target_path = "file:///" + p.replace('\\', '/')

        from PySide6.QtWidgets import QInputDialog
        options = [
            "1. 🌙 Dark Overlay 60% (Highlights WHITE text)",
            "2. 🌘 Dark Overlay 80% (Extra dark, best for bright images)",
            "3. 🌞 Light Overlay 70% (Highlights BLACK text)",
            "4. 🌌 Gradient Overlay (Darkens towards bottom, great for banners)",
            "5. ❌ No overlay (Original image)"
        ]
        overlay_choice, ok = QInputDialog.getItem(self, "Background Image Processing", "Overly detailed images can make text hard to read.\nSelect an overlay to apply over the image:", options, 0, False)
        
        if not ok: return
        
        self.save_state_for_undo()
        st = str(t.get('style', '')).strip()
        import re

        st = re.sub(r'background-image:\s*[^;]+;?', '', st)
        st = re.sub(r'background-size:\s*[^;]+;?', '', st)
        st = re.sub(r'background-position:\s*[^;]+;?', '', st)

        bg_url = f"url('{target_path}')"

        if "Dark Overlay 60%" in overlay_choice:
            bg_image = f"linear-gradient(rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0.6)), {bg_url}"
        elif "Dark Overlay 80%" in overlay_choice:
            bg_image = f"linear-gradient(rgba(0, 0, 0, 0.8), rgba(0, 0, 0, 0.8)), {bg_url}"
        elif "Light Overlay" in overlay_choice:
            bg_image = f"linear-gradient(rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0.7)), {bg_url}"
        elif "Gradient" in overlay_choice:
            bg_image = f"linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.1) 100%), {bg_url}"
        else:
            bg_image = bg_url

        new_rules = f"background-image: {bg_image}; background-size: cover; background-position: center;"
        t['style'] = st.strip('; ') + ("; " if st.strip() else "") + new_rules

        self.on_item_clicked(item, 0)
        self.apply_changes()
        self.statusBar().showMessage(f"✅ Background image set with mode: {overlay_choice.split(' ')[1]}", 6000)

    def lock_floating_image(self, item, t):
        self.save_state_for_undo()

        wrapper = t if 'image-wrapper-free' in t.get('class', []) else t.parent
        
        if wrapper and 'image-wrapper-free' in wrapper.get('class', []):
            st = str(wrapper.get('style', '')).strip()
            import re

            st = re.sub(r'resize:\s*both;?', 'resize: none;', st)
            st = re.sub(r'overflow:\s*hidden;?', 'overflow: visible;', st)
            
            wrapper['style'] = st.strip('; ')

            self.on_item_clicked(item, 0)
            self.apply_changes()
            
            self.statusBar().showMessage("🔒 Locked Image Frame (Disabled bottom-right resize handle).", 5000)
        else:
            self.statusBar().showMessage("⚠️ Please select a Free Floating Image Frame to lock.", 3000)

    def toggle_resize_block(self, item, t):
        self.save_state_for_undo()
        st = str(t.get('style', '')).strip()
        import re

        if 'resize:' in st and 'both' in st:
            st = re.sub(r'resize:\s*both;?', 'resize: none;', st)
            st = re.sub(r'overflow:\s*auto;?', 'overflow: visible;', st)
            st = re.sub(r'overflow:\s*hidden;?', 'overflow: visible;', st)
            msg = "🔒 Resizing handle DISABLED for this block."
        else:
            st = re.sub(r'resize:\s*none;?', '', st)
            st = st.strip(';') + ("; " if st else "") + "resize: both; overflow: hidden;"
            msg = "📐 Resizing handle ENABLED! Resize from the bottom-right corner."

        t['style'] = st.strip('; ')
        self.on_item_clicked(item, 0)
        self.apply_changes()
        self.statusBar().showMessage(msg, 5000)

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
            
        self.statusBar().showMessage("🔄 Reversed order of child elements!", 3000)
       
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
                self.statusBar().showMessage(f"👯 Macro Complete: Duplicated main block + {len(companions)} linked satellite blocks!", 5000)
            else:
                self.statusBar().showMessage("👯 Duplicated independently.", 5000)
                
        except Exception as e:
            self.statusBar().showMessage(f"⚠️ Macro Error: {str(e)}", 7000)

    def insert_new_image_relative(self, item, t, position):
        if not self.current_file_path:
            QMessageBox.warning(self, "Error", "Please open an HTML file.")
            return

        base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
        p, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not p: return
        
        try:
            target_path = os.path.relpath(p, base_dir).replace('\\', '/')
        except ValueError:
            target_path = "file:///" + p.replace('\\', '/')
            
        self.save_state_for_undo()

        wrapper = self.soup.new_tag('div')
        wrapper['class'] = 'image-wrapper-free'
        wrapper_style = "position: relative; display: inline-block; width: 350px; height: 250px; resize: both; overflow: hidden; border-radius: 8px; max-width: 100%; min-width: 50px; min-height: 50px; box-sizing: border-box; transition: none !important;"
        
        new_img = self.soup.new_tag('img', src=target_path)
        new_img['style'] = "width: 100%; height: 100%; object-fit: cover; display: block;"
        wrapper.append(new_img)

        if position in ["above", "below"]:
            wrapper['style'] = wrapper_style + " margin: 15px 0;"
            if position == "above": t.insert_before(wrapper)
            else: t.insert_after(wrapper)
            
        elif position in ["left", "right"]:
            main_wrapper = self.soup.new_tag('div')
            main_wrapper['class'] = "grid-wrap"
            main_wrapper['style'] = "display: grid; grid-template-columns: 1fr 1fr; gap: 15px; width: 100%; align-items: start;"
            
            t_wrapper = self.soup.new_tag('div')
            t_wrapper['class'] = "grid-item-text"
            t_wrapper['style'] = "min-width: 0; width: 100%;"
            
            img_wrapper = self.soup.new_tag('div')
            img_wrapper['class'] = "grid-item-img"
            img_wrapper['style'] = "min-width: 0; width: 100%; display: flex; justify-content: center;"

            wrapper['style'] = "position: relative; display: inline-block; width: 100%; height: 250px; resize: both; overflow: hidden; border-radius: 8px; max-width: 100%; min-width: 50px; min-height: 50px; box-sizing: border-box; transition: none !important;"
            img_wrapper.append(wrapper)
            
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
        
        new_id = str(id(wrapper))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage("✅ Image inserted! Drag the bottom-right handle to adjust size easily.", 6000)

    def insert_new_image_inside(self, item, t, position):
        if not self.current_file_path:
            QMessageBox.warning(self, "Error", "Please open a file first.")
            return

        base_dir = os.path.dirname(os.path.abspath(self.current_file_path))
        p, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not p: return
        
        try:
            target_path = os.path.relpath(p, base_dir).replace('\\', '/')
        except ValueError:
            target_path = "file:///" + p.replace('\\', '/')
            
        self.save_state_for_undo()
        
        wrapper = self.soup.new_tag('div')
        wrapper['class'] = 'image-wrapper-free'
        
        new_img = self.soup.new_tag('img', src=target_path)
        new_img['style'] = "width: 100%; height: 100%; object-fit: cover; display: block;"
        wrapper.append(new_img)

        base_style = "position: relative; resize: both; overflow: hidden; border-radius: 8px; max-width: 100%; min-width: 50px; min-height: 50px; box-sizing: border-box; transition: none !important; "
        
        if position == "left":
            wrapper['style'] = base_style + "width: 250px; height: 180px; float: left; margin: 0 15px 15px 0;"
            t.insert(0, wrapper) 
        elif position == "right":
            wrapper['style'] = base_style + "width: 250px; height: 180px; float: right; margin: 0 0 15px 15px;"
            t.insert(0, wrapper) 
        elif position == "top":
            wrapper['style'] = base_style + "width: 100%; height: 250px; display: block; margin: 0 auto 15px auto;"
            t.insert(0, wrapper) 
        elif position == "bottom":
            wrapper['style'] = base_style + "width: 100%; height: 250px; display: block; margin: 15px auto 0 auto;"
            t.append(wrapper) 

        if position in ["left", "right"]:
            st = str(t.get('style', '')).strip()
            if 'overflow' not in st: st = st.strip(';') + ("; " if st else "") + "overflow: hidden;"
            t['style'] = st.strip('; ')
                
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(wrapper))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage("✅ Inserted inline image! Drag the bottom-right handle to scale.", 6000)

    def insert_component_relative(self, item, t, position, comp_type):
        self.save_state_for_undo()
        
        html_str = ''
        if comp_type == "table":
            html_str = '<div style="overflow-x:auto;padding:10px;width:100%;"><table style="width:100%;border-collapse:collapse;margin:15px 0;font-family:sans-serif;color:inherit;"><tr style="background:#007acc;color:white;text-align:left;"><th style="padding:12px 15px;">ID</th><th style="padding:12px 15px;">Full Name</th><th style="padding:12px 15px;">Status</th></tr><tr style="border-bottom: 1px solid rgba(150,150,150,0.3);"><td style="padding:12px 15px;">#01</td><td style="padding:12px 15px;">John Doe</td><td style="padding:12px 15px;"><span style="background:#28a745;color:white;padding:4px 8px;border-radius:12px;font-size:12px;">Active</span></td></tr></table></div>'
            
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
        self.statusBar().showMessage(f"✅ Inserted Table safely at position ({position})!", 4000)

    def add_blank_layer(self, item, t, mode):
        if mode == "inside" and hasattr(self, 'check_locked') and self.check_locked(t):
            QMessageBox.warning(self, "CSS Protection", "This block is currently 🔒 LOCKED.\nCannot insert child elements inside to prevent layout breakage!\n\nPlease use 'Sibling' insertion mode instead.")
            return

        self.save_state_for_undo()
        blank_div = self.soup.new_tag('div')

        blank_div['class'] = "layer-wrapper"
        blank_div['style'] = "min-height: 100px; padding: 20px; background: rgba(0,0,0,0.03); border: 2px dashed #007acc; width: 100%; box-sizing: border-box; margin-bottom: 15px;"
        blank_div.string = "New layer content..."

        if mode == "inside":
            t.append(blank_div)
            msg = "📥 Added 1 blank layer INSIDE this element!"
        else:
            if t.name in ['body', 'html']:
                QMessageBox.warning(self, "Logic Warning", "The Body tag is top-level and cannot have siblings. Automatically switched to inside (Child) insertion!")
                t.append(blank_div)
                msg = "📥 Added 1 blank layer INSIDE the Body tag."
            else:
                t.insert_after(blank_div)
                msg = "📌 Added 1 blank layer SIBLING to this element!"

        self.refresh_tree()
        self.update_preview()

        new_id = str(id(blank_div))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(msg, 5000)

    def add_sub_item(self, item, t):
        from PySide6.QtWidgets import QMessageBox
        if hasattr(self, 'check_locked') and self.check_locked(t):
            QMessageBox.warning(self, "CSS Protection", "This element is 🔒 LOCKED.\nCannot insert Sub-menu items inside!")
            return

        if t.find_parent('nav') or 'pagination' in t.get('class', []) or t.find_parent(class_='pagination-wrapper'):
            QMessageBox.warning(self, "Structure Protection", "The 'Add Sub-menu Item' feature is only supported for vertical Sidebar menus.\nApplying it to horizontal navigation or pagination will break the layout!")
            return

        self.save_state_for_undo()
        import random

        target = t
        if target.name == 'li' and target.find('a'): target = target.find('a')

        target_folder = None
        is_creating_new_folder = False

        parent_folder = target.find_parent(class_='menu-con')
        if parent_folder:
            target_folder = parent_folder
        elif 'menu-con' in target.get('class', []):
            target_folder = target
        else:
            menu_id = target.get('data-menu')
            if menu_id: target_folder = self.soup.find(id=menu_id)
            if not target_folder:
                nxt = target.find_next_sibling()
                if nxt and 'menu-con' in nxt.get('class', []): target_folder = nxt

            if not target_folder:
                is_creating_new_folder = True

        new_page_id = f"trang-con-{random.randint(10000, 99999)}"
        js_tab_switch = "var tId=this.getAttribute('data-trang'); document.querySelectorAll('.trang-noi-dung').forEach(function(el){el.classList.remove('trang-dang-hien-thi'); el.style.display='none';}); var target=document.getElementById(tId); if(target){target.classList.add('trang-dang-hien-thi'); target.style.display='block';} document.querySelectorAll('.nut-chuyen-trang').forEach(function(btn){btn.classList.remove('menu-dang-chon'); if(btn.getAttribute('data-trang')===tId) btn.classList.add('menu-dang-chon');});"
        safe_a_style = "display: flex; align-items: center; justify-content: space-between; padding: 10px 15px; margin-bottom: 5px; color: #a0aec0; text-decoration: none; border-radius: 8px; transition: 0.2s; font-size: 13.5px;"
        
        parent_name = target.get_text(strip=True).replace('▼', '').strip() if target else "Category"

        if is_creating_new_folder:
            menu_id = f"menu-con-{random.randint(1000, 9999)}"
            
            target_folder = self.soup.new_tag('div', id=menu_id)
            target_folder['class'] = "menu-con mo-ra"
            target_folder['style'] = "display: block; margin-left: 15px; padding-left: 10px; border-left: 1px solid #2a3441; margin-bottom: 10px;"
            target.insert_after(target_folder)

            old_data_trang = target.get('data-trang')
            if 'data-trang' in target.attrs: del target['data-trang']

            classes = target.get('class', [])
            if isinstance(classes, str): classes = [classes]
            classes = [c for c in classes if c not in ['nut-chuyen-trang', 'menu-dang-chon']]
            if 'nut-mo-menu-con' not in classes: classes.append('nut-mo-menu-con')
            if 'xo-menu' not in classes: classes.append('xo-menu')
            target['class'] = classes
            target['data-menu'] = menu_id
            
            st = str(target.get('style', ''))
            if 'cursor: pointer' not in st and 'cursor:pointer' not in st:
                target['style'] = st.strip(';') + ("; " if st else "") + "cursor: pointer;"
            
            target['onclick'] = f"var m=document.getElementById('{menu_id}'); if(m.classList.contains('mo-ra')){{ m.classList.remove('mo-ra'); m.style.display='none'; this.classList.remove('xo-menu'); }} else {{ m.classList.add('mo-ra'); m.style.display='block'; this.classList.add('xo-menu'); }}"
            
            if not target.find('span', class_='mui-ten'):
                target.clear()
                span_text = self.soup.new_tag('span')
                span_text.string = parent_name
                target.append(span_text)
                
                icon = self.soup.new_tag('span')
                icon['class'] = 'mui-ten'
                icon['style'] = "font-size: 10px; transition: 0.2s;"
                icon.string = "▼"
                target.append(" ")
                target.append(icon)

            child_1 = self.soup.new_tag('a')
            child_1['class'] = "nut-chuyen-trang"
            child_1['style'] = safe_a_style
            child_1['data-trang'] = old_data_trang if old_data_trang else f"trang-con-{random.randint(10000, 99999)}"
            child_1['onclick'] = js_tab_switch
            child_1.string = f"↳ a. {parent_name} (Main)"
            target_folder.append(child_1)

            new_child = self.soup.new_tag('a')
            new_child['class'] = ["nut-chuyen-trang", "menu-dang-chon"]
            new_child['style'] = safe_a_style
            new_child['data-trang'] = new_page_id
            new_child['onclick'] = js_tab_switch
            new_child.string = "↳ b. New sub-item"
            target_folder.append(new_child)
            
            msg = "📘 Converted Category into a folder header, keeping old content and creating a new empty sub-item (b)!"

        else:
            sample_child = target_folder.find('a')
            if sample_child:
                new_child = self.clone_node(sample_child)
            else:
                new_child = self.soup.new_tag('a')
                new_child['style'] = safe_a_style

            cls = new_child.get('class', [])
            if isinstance(cls, str): cls = [cls]
            if 'menu-dang-chon' in cls: cls.remove('menu-dang-chon')
            if 'nut-chuyen-trang' not in cls: cls.append('nut-chuyen-trang')
            cls.append('menu-dang-chon')
            new_child['class'] = cls
            
            new_child['data-trang'] = new_page_id
            new_child['onclick'] = js_tab_switch
            
            child_count = len([c for c in target_folder.children if c.name == 'a'])
            char_prefix = chr(97 + child_count) if child_count < 26 else str(child_count + 1)
            new_child.string = f"↳ {char_prefix}. New sub-item"
            
            target_folder.append(new_child)

            folder_cls = target_folder.get('class', [])
            if isinstance(folder_cls, str): folder_cls = [folder_cls]
            if 'mo-ra' not in folder_cls: folder_cls.append('mo-ra')
            target_folder['class'] = folder_cls
            target_folder['style'] = str(target_folder.get('style', '')).replace('display: none', 'display: block')
            
            msg = "📥 Inserted 1 Sub-item into the existing menu!"

        for old_btn in self.soup.find_all(class_='menu-dang-chon'):
            if old_btn == new_child: continue 
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
        title.string = "Workspace: New Sub-item"
        new_page.append(title)
        
        box = self.soup.new_tag('div')
        box['class'] = "khung-bai-viet"
        box['style'] = "border: 2px dashed #00d9ff; min-height: 300px; padding: 30px; margin-top: 20px;"
        
        desc = self.soup.new_tag('h3')
        desc['style'] = "color: #00d9ff; margin-bottom: 10px;"
        desc.string = "Empty Workspace Area"
        box.append(desc)
        
        desc2 = self.soup.new_tag('p')
        desc2.string = "This page is linked 1-1 with the sub-item you just created. Drag and drop elements or tables here."
        box.append(desc2)
        new_page.append(box)

        if existing_pages:
            existing_pages[-1].insert_after(new_page)
        else:
            main_content = self.soup.find(class_='vung-noi-dung-chinh') or self.soup.find('main') or self.soup.find(class_='content-area') or self.soup.find(class_='main-content')
            if main_content: main_content.append(new_page)
            else:
                body = self.soup.find('body')
                footer = self.soup.find('footer')
                if footer: footer.insert_before(new_page)
                else: body.append(new_page)

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
        <h1 style="color: #00d2ff; margin-top: 0;">Detailed Content...</h1>
        <p style="color: #aaa; line-height: 1.6;">You can drag and drop tables, layouts, or text here to design the page.</p>
    </div>
</body>
</html>"""

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(blank_html)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot create destination page:\n{str(e)}")
            return

        rel_path = f"New_html/{filename}"

        if t.name == 'button':
            t.name = 'a'
            t['href'] = rel_path
            msg = f"🔗 Converted Button to Link targeting: {filename}"
        elif t.name == 'a':
            t['href'] = rel_path
            msg = f"🔗 Updated Link targeting: {filename}"
        else:
            new_a = self.soup.new_tag('a', href=rel_path)
            new_a['style'] = "text-decoration: none; color: inherit; display: block;"
            t.wrap(new_a)
            msg = f"🔗 Wrapped a Link targeting: {filename}"
            t = new_a 
            
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(t))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(msg, 5000)

        reply = QMessageBox.question(self, "Navigate Page", f"Created target page: {filename} and linked successfully!\n\nDo you want to open that page now to edit its content?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.current_file_path:
                self.execute_save(self.current_file_path)

            self.load_template_file(filepath)

    def create_collapsible_content(self, item, t):
        if hasattr(self, 'check_locked') and t.get('data-locked') == 'true':
            QMessageBox.information(self, "Tip", "This button is Locked. The tool will intelligently place the Collapsible Content Block immediately below it to protect your CSS structure!")

        self.save_state_for_undo()
        import random
        
        box_id = f"collapse_box_{random.randint(10000, 99999)}"
        hidden_box = self.soup.new_tag('div', id=box_id)
        hidden_box['style'] = "display: block; padding: 20px; margin-top: 5px; margin-bottom: 15px; background-color: rgba(150,150,150,0.05); border-left: 3px solid #ff9800; border-radius: 4px; width: 100%; box-sizing: border-box;"
        hidden_box.string = "Collapsible content block... (Click the item above to Toggle this block). Drag and drop other elements inside!"
        
        current_style = str(t.get('style', ''))
        if 'cursor: pointer' not in current_style:
            t['style'] = current_style.strip(';') + ("; " if current_style else "") + "cursor: pointer;"
            
        t['onclick'] = f"var el = document.getElementById('{box_id}'); if(el.style.display === 'none' || el.style.display === '') {{ el.style.display = 'block'; }} else {{ el.style.display = 'none'; }}"
        t.insert_after(hidden_box)
        
        self.refresh_tree()
        self.update_preview()
        
        new_id = str(id(hidden_box))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage("🔽 Created Collapsible Content block! On the live webpage, clicking the element above will Toggle this block.", 7000)

    def insert_inner_pagination(self, item, t):
        self.save_state_for_undo()
        import random
        from PySide6.QtWidgets import QMessageBox

        if hasattr(self, 'check_locked') and t.get('data-locked') == 'true':
            QMessageBox.warning(self, "CSS Protection", "This block is 🔒 LOCKED. Cannot insert internal pagination inside!")
            return

        pag_id = f"inner-pag-{random.randint(10000, 99999)}"
        
        js_pag_switch = "var p=this.closest('.pagination-wrapper');var act=this.getAttribute('data-action');var pId=this.getAttribute('data-page');var pgs=Array.from(p.querySelectorAll('.phan-trang-noi-dung'));var btns=Array.from(p.querySelectorAll('.nut-phan-trang'));var cIdx=pgs.findIndex(x=>x.style.display==='block');if(cIdx<0)cIdx=0;var nIdx=cIdx;if(act==='first')nIdx=0;if(act==='last')nIdx=pgs.length-1;if(act==='prev')nIdx=Math.max(0,cIdx-1);if(act==='next')nIdx=Math.min(pgs.length-1,cIdx+1);if(pId)nIdx=pgs.findIndex(x=>x.id===pId);if(nIdx<0)return;pgs.forEach((el,i)=>el.style.display=(i===nIdx)?'block':'none');p.querySelectorAll('.pag-dots').forEach(d=>d.remove());var aBg=btns.length>0?(btns[0].getAttribute('data-active-bg')||'#007acc'):'#007acc';btns.forEach((b,i)=>{if(i===nIdx){b.style.background=aBg;b.style.color='#fff';b.style.boxShadow='0 0 10px '+aBg;}else{b.style.background='transparent';b.style.color='inherit';b.style.boxShadow='none';}var disp=b.getAttribute('data-disp')||'inline-block';if(btns.length>5){if(i===0||i===btns.length-1||(i>=nIdx-1&&i<=nIdx+1)){b.style.display=disp;if(i===nIdx-1&&i>1){var d1=document.createElement('span');d1.className='pag-dots';d1.innerHTML='...';d1.style.padding='0 5px';b.parentNode.insertBefore(d1,b);}if(i===btns.length-1&&nIdx<btns.length-3){var d2=document.createElement('span');d2.className='pag-dots';d2.innerHTML='...';d2.style.padding='0 5px';b.parentNode.insertBefore(d2,b);}}else{b.style.display='none';}}else{b.style.display=disp;}});"

        html = f'''
        <div class="pagination-wrapper" style="width:100%; margin:20px 0; border: 1px dashed rgba(150,150,150,0.5); padding: 15px; border-radius: 8px; box-sizing: border-box;">
            <div id="{pag_id}-1" class="phan-trang-noi-dung" style="display:block; min-height:150px; width:100%; margin-bottom:20px;">
                <h3 style="margin-top:0; color:#007acc;">Page 1 Content (Internal)</h3>
                <p style="opacity:0.7;">Drag and drop text, tables, images... here.</p>
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
            
        self.statusBar().showMessage("🔢 Inserted Internal Pagination component successfully!", 5000)

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
            msg = "🔓 UNLOCKED! You can now freely insert elements inside."
        else:
            t['data-locked'] = 'true'
            msg = "🔒 STRUCTURE LOCKED! Preventing child insertion to safeguard CSS layout."
        
        self.refresh_tree()
        self.update_preview()
        new_id = str(id(t))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        self.statusBar().showMessage(msg, 5000)

    def attach_safe_link(self, item, t):
        from PySide6.QtWidgets import QInputDialog

        url, ok = QInputDialog.getText(self, "Attach Safe Link (Preserve layout)", "Enter web URL or filename to download:\n(Example: https://google.com or document.pdf)")
        
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
            
            self.statusBar().showMessage(f"🧲 Successfully attached hidden link to <{t.name}>! Button structure remains 100% intact.", 6000)

    def edit_raw_html(self, item, t):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QMessageBox
        import copy
        
        self.save_state_for_undo()

        dialog = QDialog(self)
        dialog.setWindowTitle(f"🛠️ Edit Raw HTML: <{t.name}>")
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
        btn_save = QPushButton("💾 SAVE AND OVERWRITE THIS ELEMENT")
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
                
            self.statusBar().showMessage("✅ Successfully overwrote raw HTML code!", 5000)
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
            .hover-scale { transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), box-shadow 0.3s ease !important; }
            .hover-scale:hover { transform: translateY(-5px) scale(1.03) !important; box-shadow: 0 15px 25px rgba(0,0,0,0.2) !important; z-index: 10; }

            .hover-glow { transition: all 0.3s ease !important; }
            .hover-glow:hover { box-shadow: 0 0 15px #00d2ff, 0 0 30px #00d2ff !important; border-color: #00d2ff !important; z-index: 10; }

            .hover-opacity { transition: opacity 0.3s ease !important; }
            .hover-opacity:hover { opacity: 0.6 !important; }

            .hover-neon { transition: all 0.3s ease !important; }
            .hover-neon:hover { box-shadow: 0 0 10px #ff00ff, 0 0 20px #00ffff, 0 0 30px #00ff00 !important; border-color: #fff !important; z-index: 10; }

            .hover-tilt { transition: transform 0.4s ease, box-shadow 0.4s ease !important; }
            .hover-tilt:hover { transform: perspective(1000px) rotateX(8deg) rotateY(-8deg) scale(1.02) !important; box-shadow: -10px 10px 20px rgba(0,0,0,0.3) !important; z-index: 10; }

            @keyframes hoverWiggle { 0% {transform: rotate(0deg);} 25% {transform: rotate(-3deg);} 50% {transform: rotate(3deg);} 75% {transform: rotate(-3deg);} 100% {transform: rotate(0deg);} }
            .hover-wiggle:hover { animation: hoverWiggle 0.4s ease-in-out infinite !important; z-index: 10; }

            .hover-color { filter: grayscale(100%) !important; transition: filter 0.5s ease, transform 0.3s ease !important; }
            .hover-color:hover { filter: grayscale(0%) !important; transform: scale(1.02) !important; }

            .hover-outline { transition: outline-offset 0.3s ease, outline-color 0.3s ease !important; outline: 2px solid transparent !important; outline-offset: 0px !important; }
            .hover-outline:hover { outline-color: #00d2ff !important; outline-offset: 8px !important; }
            """
            head.append(style_tag)
            
        from PySide6.QtWidgets import QInputDialog
        items = [
            "1. Scale Up & Float (Scale & Shadow)", 
            "2. Blue Border Glow (Glow)", 
            "3. Fade Out (Opacity)",
            "4. 🌈 Multi-color Neon Glow (Neon)",
            "5. 🧊 3D Tilt Effect",
            "6. 🔔 Wiggle Attention (Wiggle)",
            "7. 🎨 Grayscale -> Color (Best for Images)",
            "8. 🔲 Expanding Outline (Outline Offset)"
        ]
        effect, ok = QInputDialog.getItem(self, "Select Hover Effect", "When mouse hovers over this element:", items, 0, False)
        
        if ok and effect:
            classes = t.get('class', [])
            if isinstance(classes, str): classes = [classes]

            all_hover_classes = ['hover-scale', 'hover-glow', 'hover-opacity', 'hover-neon', 'hover-tilt', 'hover-wiggle', 'hover-color', 'hover-outline']
            classes = [c for c in classes if c not in all_hover_classes]
            
            if "Scale Up" in effect: classes.append("hover-scale")
            elif "Blue Border Glow" in effect: classes.append("hover-glow")
            elif "Fade Out" in effect: classes.append("hover-opacity")
            elif "Neon" in effect: classes.append("hover-neon")
            elif "3D Tilt" in effect: classes.append("hover-tilt")
            elif "Wiggle" in effect: classes.append("hover-wiggle")
            elif "Grayscale" in effect: classes.append("hover-color")
            elif "Expanding Outline" in effect: classes.append("hover-outline")
            
            t['class'] = classes
            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage(f"✨ Applied hover effect to <{t.name}>!", 4000)

    def make_collapsible_menu(self, item, t):
        self.save_state_for_undo()

        next_sibling = t.find_next_sibling()
        
        if not next_sibling or 'sub-menu-folder' not in next_sibling.get('class', []):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Sub-menu Folder Not Found", "No Sub-menu folder found below this item.\n\nPlease use 'Add Sub-menu Item to Menu' first before toggling collapsible functionality.")
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
        self.statusBar().showMessage("↕️ Enabled Collapse/Expand (Dropdown) functionality!", 5000)

    def add_pagination_page(self, pag_container):
        self.save_state_for_undo()
        import random

        wrapper = pag_container.parent
        if not wrapper or wrapper.name in ['body', 'html'] or 'pagination-wrapper' not in wrapper.get('class', []):
            wrapper = pag_container.find_parent(class_='pagination-wrapper')
            
        if not wrapper:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Structure Error", "This pagination block is not inside a wrapper container (pagination-wrapper). Please use a pagination template from the Library!")
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
        desc.string = f"Empty area for page {next_num}. Drag and drop elements or tables here."
        new_content_div.append(desc)

        btn_container.insert_before(new_content_div)

        self.refresh_tree()
        self.update_preview()

        js_init = f"var wrapper = document.getElementById('{new_page_id}').closest('.pagination-wrapper'); if(wrapper) {{ var activeBtn = wrapper.querySelector('.nut-phan-trang[style*=\"{active_bg}\"]'); if(!activeBtn) activeBtn = wrapper.querySelector('.nut-phan-trang'); if(activeBtn) activeBtn.click(); }}"
        self.web_view.page().runJavaScript(js_init)
        
        new_id = str(id(new_content_div))
        if new_id in self.node_map: self.select_tree_item_by_id(new_id)
        
        self.statusBar().showMessage(f"📄 Created Page {next_num}! (Auto collapses to ellipsis '...' when exceeding 5 pages)", 4000)

    def add_blank_page_to_menu(self, item, t):
        from PySide6.QtWidgets import QMessageBox
        
        target_btn = t
        if t.name == 'li':
            a_tag = t.find('a')
            if a_tag: target_btn = a_tag

        if 'pagination' in target_btn.get('class', []) or target_btn.find_parent(class_='pagination-wrapper') or target_btn.find_parent(class_='pagination') or 'nut-phan-trang' in target_btn.get('class', []):
            QMessageBox.warning(self, "Structure Protection", "Pagination areas have dedicated page switching algorithms (with ellipsis ellipsis).\nDo not use 'Create Blank Tab Page' here as it will overwrite and break pagination!")
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
        desc.string = "This new content page has been linked to your selected button. Drag and drop components from the library here to design."
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
        
        self.statusBar().showMessage(f"📄 Created a blank page linked to button: {parent_name}!", 6000)

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
            QMessageBox.warning(self, "Error", "Cannot add sibling category at this location.")
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
                s.replace_with("New Category")
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
        
        self.statusBar().showMessage("➖ Added sibling category!", 4000)

    def copy_element(self, item, t): 
        self.clipboard_node = self.clone_node(t)
        self.statusBar().showMessage(f"📋 Copied <{t.name}> to temporary clipboard!", 3000)

    def cut_element(self, item, t):
        self.save_state_for_undo()
        self.clipboard_node = self.clone_node(t)
        t.decompose()
        self.refresh_tree()
        self.update_preview()
        self.statusBar().showMessage(f"✂️ Cut <{t.name}>!", 3000)

    def paste_element(self, item, t, mode):
        if not self.clipboard_node: return
        self.save_state_for_undo()
        pt = self.clone_node(self.clipboard_node)
        if mode == "inside": t.append(pt)
        else: t.insert_after(pt)
        self.refresh_tree()
        self.update_preview()
        self.statusBar().showMessage("📌 Pasted successfully!", 3000)

    def delete_html_element(self, item, t):
        if QMessageBox.question(self, "Confirm Deletion", f"Are you sure you want to delete <{t.name}>?") == QMessageBox.StandardButton.Yes:
            self.save_state_for_undo()
            t.decompose()
            self.refresh_tree()
            self.update_preview()
            self.statusBar().showMessage("🗑️ Deleted element!", 3000)

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
        btn_active = "background: #007acc; padding: 5px 12px; border-radius: 4px; font-weight: bold; color: white;"
        btn_inactive = "background: #4d4d4d; padding: 5px 12px; border-radius: 4px; font-weight: bold; color: white;"
        
        if mode == "mobile":
            self.web_view.setMinimumWidth(414)
            self.web_view.setMaximumWidth(414)

            self.spacer_left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.spacer_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.spacer_left.show()
            self.spacer_right.show()

            self.web_container.setStyleSheet("background-color: #050505;")
            
            self.btn_mobile.setStyleSheet(btn_active)
            self.btn_desktop.setStyleSheet(btn_inactive)
            self.statusBar().showMessage("📱 Viewing in Mobile mode (Simulating 414px width)", 4000)
            
        else:
            self.web_view.setMinimumWidth(0)
            self.web_view.setMaximumWidth(16777215)

            self.spacer_left.hide()
            self.spacer_right.hide()
            
            self.web_container.setStyleSheet("background-color: #111111;")
            
            self.btn_desktop.setStyleSheet(btn_active)
            self.btn_mobile.setStyleSheet(btn_inactive)
            self.statusBar().showMessage("🖥️ Viewing in Desktop mode (Full screen)", 4000)

    def change_zoom(self, zoom_str):
        try:
            user_zoom = float(zoom_str.replace('%', '')) / 100.0
            dpi_scale = self.devicePixelRatioF()
            true_zoom_factor = user_zoom / dpi_scale
            
            self.web_view.setZoomFactor(true_zoom_factor)
            self.statusBar().showMessage(f"🔍 Web Zoom: {zoom_str} (Automatically offset for Windows {dpi_scale}x DPI)", 4000)
        except Exception:
            self.web_view.setZoomFactor(1.0)
            self.cb_zoom.setCurrentText("100%")

    def refresh_library(self):
        from PySide6.QtWidgets import QTreeWidgetItem
        from PySide6.QtCore import Qt
        
        comp_dir = os.path.join(BASE_DIR, 'components')
        if not os.path.exists(comp_dir): os.makedirs(comp_dir)

        if hasattr(self, 'list_library'):
            self.list_library.clear()

            def build_tree(current_dir, parent_node):
                items = sorted(os.listdir(current_dir))
                folders = [i for i in items if os.path.isdir(os.path.join(current_dir, i))]
                files = [i for i in items if os.path.isfile(os.path.join(current_dir, i))]

                for folder in folders:
                    folder_path = os.path.join(current_dir, folder)
                    folder_item = QTreeWidgetItem(parent_node, [f"📂 {folder}"])

                    build_tree(folder_path, folder_item)

                for f in files:
                    if f.lower().endswith(('.html', '.htm')):
                        base_name = os.path.splitext(f)[0]
                        file_path = os.path.join(current_dir, f)
                        tree_item = QTreeWidgetItem(parent_node, [f"📦 {base_name}"])

                        tree_item.setData(0, Qt.ItemDataRole.UserRole, file_path)

            build_tree(comp_dir, self.list_library.invisibleRootItem())
            self.list_library.expandAll()

            try: self.list_library.itemDoubleClicked.disconnect()
            except: pass
            self.list_library.itemDoubleClicked.connect(self.insert_from_library)
            
            self.statusBar().showMessage("📦 Reloaded Component Tree Library successfully!", 3000)

    def insert_from_library(self, *args):
        item = self.list_library.currentItem()
            
        if not item:
            QMessageBox.warning(self, "No Item Selected", "Please select an HTML block (📦) from the list to insert!")
            return

        html_path = item.data(0, Qt.ItemDataRole.UserRole)

        if not html_path:
            QMessageBox.information(self, "Directory Selected", "You selected a folder 📂.\nPlease expand it and double-click an item 📦 inside to insert.")
            return

        base_dir = os.path.dirname(html_path)
        base_name = os.path.splitext(os.path.basename(html_path))[0]

        css_path = os.path.join(base_dir, f"{base_name}.css")
        js_path = os.path.join(base_dir, f"{base_name}.js")

        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                final_content = f.read()

            has_css = False; has_js = False

            if os.path.exists(css_path):
                with open(css_path, 'r', encoding='utf-8') as f:
                    css_content = f.read()
                if css_content.strip():
                    final_content = f"<style /* comp-css: {base_name} */>\n{css_content.strip()}\n</style>\n" + final_content
                    has_css = True

            if os.path.exists(js_path):
                with open(js_path, 'r', encoding='utf-8') as f:
                    js_content = f.read()
                if js_content.strip():
                    safe_js = f"/* comp-js: {base_name} */\n(function(){{\n{js_content.strip()}\n}})();"
                    final_content = final_content + f"\n<script>\n{safe_js}\n</script>"
                    has_js = True

            self.insert_quick_component(final_content)

            msg = f"✅ Inserted block [{base_name}]"
            if has_css and has_js: msg += " (With CSS & JS)"
            elif has_css: msg += " (With CSS)"
            elif has_js: msg += " (With JS)"

            self.statusBar().showMessage(msg, 5000)
                
        except Exception as e:
            QMessageBox.critical(self, "File Read Error", f"Unable to load this component:\n{str(e)}")

    def show_template_gallery(self):
        self.view_stack.setCurrentIndex(1)
        
        tpl_dir = os.path.join(BASE_DIR, 'templates')
        os.makedirs(tpl_dir, exist_ok=True)
        
        self.tpl_tree.clear()
        self.btn_use_tpl.setEnabled(False)
        self.selected_tpl_path = None
        self.lbl_tpl_info.setText("📌 Select a template on the left to preview")

        def build_tpl_tree(current_dir, parent_node):
            items = sorted(os.listdir(current_dir))
            for item in items:
                item_path = os.path.join(current_dir, item)
                if os.path.isdir(item_path):
                    index_file = os.path.join(item_path, 'index.html')
                    if os.path.exists(index_file):
                        item_node = QTreeWidgetItem(parent_node, [f"📑 {item}"])
                        item_node.setData(0, Qt.ItemDataRole.UserRole, index_file)
                    else:
                        folder_node = QTreeWidgetItem(parent_node, [f"📂 {item}"])
                        build_tpl_tree(item_path, folder_node)
                        
        build_tpl_tree(tpl_dir, self.tpl_tree.invisibleRootItem())
        self.tpl_tree.expandAll()

    def on_tpl_tree_clicked(self, item, col):
        index_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not index_path or not os.path.exists(index_path):
            self.btn_use_tpl.setEnabled(False)
            self.selected_tpl_path = None
            self.lbl_tpl_info.setText("📂 Template directory. Expand it and click a template 📑 inside!")
            return
            
        self.selected_tpl_path = index_path
        self.btn_use_tpl.setEnabled(True)
        
        folder_dir = os.path.dirname(index_path)
        tpl_name = os.path.basename(folder_dir)

        thumb_path = ""
        for ext in ['jpg', 'png', 'jpeg', 'webp']:
            p = os.path.join(folder_dir, f"thumb.{ext}")
            if os.path.exists(p):
                thumb_path = p
                break

        if thumb_path:
            img_url = QUrl.fromLocalFile(thumb_path).toString()
            html_thumb = f"""
            <body style='margin:0; background:#1e1e1e; display:flex; justify-content:center; align-items:center; height:100vh;'>
                <img src='{img_url}' style='max-width:100%; max-height:100%; object-fit:contain; border-radius:8px; box-shadow:0 10px 25px rgba(0,0,0,0.5);'>
            </body>
            """
            self.tpl_preview.setHtml(html_thumb)
            self.lbl_tpl_info.setText(f"📑 Previewing template: <b>{tpl_name}</b> (Thumbnail Image)")
        else:
            self.tpl_preview.load(QUrl.fromLocalFile(index_path))
            self.lbl_tpl_info.setText(f"📑 Previewing live: <b>{tpl_name}</b> (Live Web Engine)")

    def prev_template_page(self):
        if self.current_tpl_page > 0:
            self.current_tpl_page -= 1
            self.update_gallery_ui()

    def next_template_page(self):
        total_pages = (len(self.template_folders) + 3) // 4
        if self.current_tpl_page < total_pages - 1:
            self.current_tpl_page += 1
            self.update_gallery_ui()
            
    def load_selected_template(self):
        if not self.selected_tpl_path or not os.path.exists(self.selected_tpl_path):
            QMessageBox.warning(self, "Error", "No valid template selected!")
            return

        if not self.check_and_save_if_dirty():
            return
            
        self.load_template_file(self.selected_tpl_path)

    def load_template_file(self, filepath):
        self.view_stack.setCurrentIndex(0)
        try:
            abs_path = os.path.abspath(filepath)
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                self.soup = self.parse_html(f.read())
            
            for s in self.soup.find_all('script'):
                if not s.has_attr('src') and not s.has_attr('id') and s.string and "EDITOR_SCROLL" in s.string:
                    s.decompose()
                    
            self._legacy_warned = False
            self.current_file_path = None 
            self.current_base_dir = os.path.dirname(abs_path)
            self.is_dirty = True
            
            if hasattr(self, 'undo_stack'): self.undo_stack.clear()
            if hasattr(self, 'redo_stack'): self.redo_stack.clear()
            
            folder_name = os.path.basename(os.path.dirname(abs_path))
            self.lbl_current_file.setText(f"Viewing: <b>Template: {folder_name} (Unsaved)</b>")
            
            self.refresh_tree(); self.update_preview()
            self.statusBar().showMessage("📑 Template loaded successfully! Press Ctrl+S to save the project locally.", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Template Loading Error", f"Unable to read template directory:\n{str(e)}")

    def closeEvent(self, event):
        if self.check_and_save_if_dirty():
            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UniversalHTMLEditor()
    window.show()
    sys.exit(app.exec())
