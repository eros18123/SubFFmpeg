
# anki_export.py

from aqt.qt import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QComboBox,
    QGridLayout, QTextEdit, QLineEdit,
    QCheckBox
)

def setup_anki_export_tab(self):
    layout = QVBoxLayout(self.tab_anki_export)
    self.anki_frame = QGroupBox()
    
    anki_frame_main_layout = QHBoxLayout()
    self.anki_frame.setLayout(anki_frame_main_layout)

    anki_grid_layout = QGridLayout()
    anki_grid_layout.setColumnStretch(1, 0) 
    anki_grid_layout.setColumnStretch(2, 1)
    row = 0

    self.deck_label_anki = QLabel(); anki_grid_layout.addWidget(self.deck_label_anki, row, 0)
    self.deck_combo = QComboBox(); self.deck_combo.setFixedWidth(350); anki_grid_layout.addWidget(self.deck_combo, row, 1); row += 1
    
    self.note_type_label_anki = QLabel(); anki_grid_layout.addWidget(self.note_type_label_anki, row, 0)
    self.note_type_combo = QComboBox(); self.note_type_combo.setFixedWidth(350); self.note_type_combo.currentIndexChanged.connect(self.update_anki_fields); anki_grid_layout.addWidget(self.note_type_combo, row, 1); row += 1
    
    self.audio_field_label_anki = QLabel(); anki_grid_layout.addWidget(self.audio_field_label_anki, row, 0)
    self.audio_field_combo = QComboBox(); self.audio_field_combo.setFixedWidth(350); anki_grid_layout.addWidget(self.audio_field_combo, row, 1); row += 1
    
    self.subtitle_field_label_anki = QLabel(); anki_grid_layout.addWidget(self.subtitle_field_label_anki, row, 0)
    self.subtitle_field_combo = QComboBox(); self.subtitle_field_combo.setFixedWidth(350); anki_grid_layout.addWidget(self.subtitle_field_combo, row, 1); row += 1
    
    self.translation_field_label_anki = QLabel(); anki_grid_layout.addWidget(self.translation_field_label_anki, row, 0)
    self.translation_field_combo = QComboBox(); self.translation_field_combo.setFixedWidth(350); anki_grid_layout.addWidget(self.translation_field_combo, row, 1); row += 1
    
    self.image_field_label_anki = QLabel(); anki_grid_layout.addWidget(self.image_field_label_anki, row, 0)
    self.image_field_combo = QComboBox(); self.image_field_combo.setFixedWidth(350); anki_grid_layout.addWidget(self.image_field_combo, row, 1); row += 1
    
    self.deck_combo.currentIndexChanged.connect(self._save_anki_export_settings)
    self.note_type_combo.currentIndexChanged.connect(self._save_anki_export_settings)
    self.audio_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)
    self.subtitle_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)
    self.translation_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)
    self.image_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)

    anki_frame_main_layout.addLayout(anki_grid_layout)
    anki_frame_main_layout.addStretch(1)

    main_v_layout = QVBoxLayout()
    main_v_layout.addWidget(self.anki_frame)

    self.folder_log_group_anki = QGroupBox()
    folder_log_layout = QVBoxLayout()

    # --- NOVO CHECKBOX DE MODO ---
    self.anki_use_folder_cb = QCheckBox()
    self.anki_use_folder_cb.stateChanged.connect(self._on_anki_source_mode_changed)
    folder_log_layout.addWidget(self.anki_use_folder_cb)
    # --- FIM NOVO ---

    # --- Seletor de Pasta de Origem ---
    source_folder_layout = QHBoxLayout()
    self.anki_source_folder_label = QLabel()
    source_folder_layout.addWidget(self.anki_source_folder_label)
    
    self.anki_source_folder_entry = QLineEdit()
    self.anki_source_folder_entry.setReadOnly(True)
    self.anki_source_folder_entry.setPlaceholderText(self.tr("anki_export.placeholder.source_folder"))
    source_folder_layout.addWidget(self.anki_source_folder_entry)
    
    self.btn_select_anki_source_folder = QPushButton()
    self.btn_select_anki_source_folder.clicked.connect(self.select_anki_source_folder)
    source_folder_layout.addWidget(self.btn_select_anki_source_folder)

    self.btn_clear_anki_source_folder = QPushButton()
    self.btn_clear_anki_source_folder.clicked.connect(self.clear_anki_source_folder)
    source_folder_layout.addWidget(self.btn_clear_anki_source_folder)

    folder_log_layout.addLayout(source_folder_layout)
    # --- FIM ---

    self.folder_files_log = QTextEdit(); self.folder_files_log.setReadOnly(True); self.folder_files_log.setFixedHeight(100)
    folder_log_layout.addWidget(self.folder_files_log)
    self.folder_log_group_anki.setLayout(folder_log_layout)
    main_v_layout.addWidget(self.folder_log_group_anki)

    buttons_hbox = QHBoxLayout()
    self.btn_list_files_anki = QPushButton()
    self.btn_list_files_anki.clicked.connect(self.list_output_folder_files)
    buttons_hbox.addWidget(self.btn_list_files_anki)

    self.add_to_anki_button = QPushButton()
    self.add_to_anki_button.clicked.connect(self.add_items_to_anki)
    buttons_hbox.addWidget(self.add_to_anki_button)
    buttons_hbox.addStretch()
    
    main_v_layout.addLayout(buttons_hbox)
    main_v_layout.addStretch()
    
    layout.addLayout(main_v_layout)