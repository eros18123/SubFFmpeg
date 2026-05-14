from aqt.qt import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QProgressBar, QComboBox,
    QGridLayout, QCheckBox, QTextEdit
)

def setup_process_tab(self):
    layout = QVBoxLayout(self.tab_process)
    
    # --- Arquivos de Entrada e Saída ---
    top_layout = QHBoxLayout()
    self.files_frame_process = QGroupBox()
    files_grid_layout = QGridLayout()
    files_grid_layout.setColumnStretch(1, 1)
    row = 0
    
    self.media_file_label_process = QLabel()
    files_grid_layout.addWidget(self.media_file_label_process, row, 0)
    self.media_entry = QLineEdit(self.media_file_path_var)
    files_grid_layout.addWidget(self.media_entry, row, 1)
    self.btn_open_media_process = QPushButton()
    self.btn_open_media_process.clicked.connect(self.select_media_file)
    files_grid_layout.addWidget(self.btn_open_media_process, row, 2); row += 1

    self.main_subtitle_label_process = QLabel()
    files_grid_layout.addWidget(self.main_subtitle_label_process, row, 0)
    self.sub_entry = QLineEdit(self.subtitle_file_path_var)
    files_grid_layout.addWidget(self.sub_entry, row, 1)
    self.btn_open_sub_process = QPushButton()
    self.btn_open_sub_process.clicked.connect(self.select_subtitle_file)
    files_grid_layout.addWidget(self.btn_open_sub_process, row, 2); row += 1

    self.translation_subtitle_label_process = QLabel()
    files_grid_layout.addWidget(self.translation_subtitle_label_process, row, 0)
    self.translation_entry = QLineEdit(self.translation_file_path_var)
    files_grid_layout.addWidget(self.translation_entry, row, 1)
    self.btn_open_translation_process = QPushButton()
    self.btn_open_translation_process.clicked.connect(self.select_translation_file)
    files_grid_layout.addWidget(self.btn_open_translation_process, row, 2); row += 1

    self.output_folder_media_label_process = QLabel()
    files_grid_layout.addWidget(self.output_folder_media_label_process, row, 0)
    self.out_entry = QLineEdit(self.output_folder_path_var)
    self.out_entry.setPlaceholderText(str(self.base_default_output_folder)) 
    files_grid_layout.addWidget(self.out_entry, row, 1)
    self.btn_select_out_process = QPushButton()
    self.btn_select_out_process.clicked.connect(self.select_output_dir)
    files_grid_layout.addWidget(self.btn_select_out_process, row, 2); row += 1
    
    self.files_frame_process.setLayout(files_grid_layout)
    top_layout.addWidget(self.files_frame_process)

    # --- Opções de Saída (ao lado) ---
    output_options_group = QGroupBox()
    output_options_layout = QVBoxLayout()
    
    self.direct_to_media_collection_cb_process = QCheckBox()
    self.direct_to_media_collection_cb_process.setChecked(self.pref_direct_process_to_cm)
    self.direct_to_media_collection_cb_process.stateChanged.connect(self._on_direct_process_to_cm_changed)
    output_options_layout.addWidget(self.direct_to_media_collection_cb_process)

    format_layout = QHBoxLayout()
    self.output_format_label_process = QLabel()
    format_layout.addWidget(self.output_format_label_process)
    self.output_format_combo = QComboBox()
    self.output_format_combo.addItems(["MP3 (áudio)", "MP4 (vídeo)", "WebM (vídeo)"])
    self.output_format_combo.setCurrentIndex(self.last_output_format_index)
    self.output_format_combo.currentIndexChanged.connect(self._on_output_format_changed)
    format_layout.addWidget(self.output_format_combo)
    output_options_layout.addLayout(format_layout)
    output_options_layout.addStretch()
    output_options_group.setLayout(output_options_layout)
    top_layout.addWidget(output_options_group)

    layout.addLayout(top_layout)

    # --- Processamento e Log ---
    processing_and_log_layout = QHBoxLayout()
    self.processing_frame_process = QGroupBox()
    process_layout = QVBoxLayout()

    self.adjust_cuts_cb = QCheckBox()
    self.adjust_cuts_cb.setChecked(self.adjust_cuts_to_silence_enabled)
    self.adjust_cuts_cb.stateChanged.connect(lambda state: self._save_config_value(self.CONFIG_KEY_ADJUST_CUTS_TO_SILENCE, bool(state)))
    process_layout.addWidget(self.adjust_cuts_cb)

    split_buttons_layout = QHBoxLayout()
    self.split_button = QPushButton(); self.split_button.clicked.connect(self.start_split_media_process)
    split_buttons_layout.addWidget(self.split_button)
    self.stop_button = QPushButton(); self.stop_button.clicked.connect(self.request_stop_processing); self.stop_button.setEnabled(False)
    split_buttons_layout.addWidget(self.stop_button)
    split_buttons_layout.addStretch()
    process_layout.addLayout(split_buttons_layout)
    self.progress_bar = QProgressBar(); self.progress_bar.setMaximum(100); self.progress_bar.setValue(0)
    process_layout.addWidget(self.progress_bar)
    self.progress_label = QLabel("0%"); process_layout.addWidget(self.progress_label)
    self.time_label = QLabel(); process_layout.addWidget(self.time_label)
    self.status_label = QLabel(); process_layout.addWidget(self.status_label)
    self.processing_frame_process.setLayout(process_layout)
    processing_and_log_layout.addWidget(self.processing_frame_process)

    self.log_frame_process = QGroupBox()
    log_layout = QVBoxLayout()
    self.log_text_area = QTextEdit(); self.log_text_area.setReadOnly(True)
    log_layout.addWidget(self.log_text_area)
    self.log_frame_process.setLayout(log_layout)
    processing_and_log_layout.addWidget(self.log_frame_process)
    
    layout.addLayout(processing_and_log_layout)
    layout.addStretch()