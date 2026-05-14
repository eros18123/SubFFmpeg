# subs_and_time.py

from aqt.qt import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QGridLayout,
    QCheckBox
)

def setup_subs_and_time_tab(self):
    layout = QVBoxLayout(self.tab_subs_and_time)

    # --- SEÇÃO PARA GERAR LEGENDAS (E TRADUÇÃO) ---
    self.generation_frame_process = QGroupBox()
    generation_v_layout = QVBoxLayout()

    self.api_info_label = QLabel()
    self.api_info_label.setWordWrap(True)
    self.api_info_label.setOpenExternalLinks(True)
    generation_v_layout.addWidget(self.api_info_label)

    api_key_h_layout = QHBoxLayout()
    self.api_key_label = QLabel()
    api_key_h_layout.addWidget(self.api_key_label)
    
    self.api_key_entry = QLineEdit(self.api_key_var)
    self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
    self.api_key_entry.textChanged.connect(self._save_api_key)
    api_key_h_layout.addWidget(self.api_key_entry)
    api_key_h_layout.addStretch()
    generation_v_layout.addLayout(api_key_h_layout)

    # Layout para botão de gerar e idioma da legenda
    button_lang_h_layout = QHBoxLayout()
    self.btn_generate_subs = QPushButton()
    self.btn_generate_subs.clicked.connect(self.start_transcription_process)
    button_lang_h_layout.addWidget(self.btn_generate_subs)

    self.transcription_lang_label = QLabel()
    button_lang_h_layout.addWidget(self.transcription_lang_label)

    self.transcription_lang_combo = QComboBox()
    self.transcription_lang_combo.addItems(["Inglês", "Português"])
    self.transcription_lang_combo.setCurrentIndex(self.last_transcription_lang_index)
    self.transcription_lang_combo.currentIndexChanged.connect(self._save_transcription_language)
    button_lang_h_layout.addWidget(self.transcription_lang_combo)
    button_lang_h_layout.addStretch()
    generation_v_layout.addLayout(button_lang_h_layout)

    # Layout para a nova opção de tradução
    translation_h_layout = QHBoxLayout()
    self.generate_translation_cb = QCheckBox()
    translation_h_layout.addWidget(self.generate_translation_cb)

    self.translation_lang_combo = QComboBox()
    self.translation_lang_combo.addItems(["Português", "Inglês"])
    translation_h_layout.addWidget(self.translation_lang_combo)
    translation_h_layout.addStretch()
    generation_v_layout.addLayout(translation_h_layout)


    self.generation_frame_process.setLayout(generation_v_layout)
    layout.addWidget(self.generation_frame_process)

    # --- Opções de Tempo ---
    time_options_layout = QHBoxLayout()

    # --- Limite por Legendas (Opcional) ---
    self.time_limit_frame = QGroupBox()
    time_limit_v_layout = QVBoxLayout()
    self.limit_time_range_cb = QCheckBox()
    self.limit_time_range_cb.setChecked(self.limit_time_range_enabled)
    self.limit_time_range_cb.stateChanged.connect(self._on_limit_time_range_toggled)
    time_limit_v_layout.addWidget(self.limit_time_range_cb)

    start_time_layout = QHBoxLayout()
    self.start_time_label = QLabel()
    start_time_layout.addWidget(self.start_time_label)
    self.start_time_entry = QLineEdit(self.limit_start_time_str)
    self.start_time_entry.setFixedWidth(120)
    self.start_time_entry.textChanged.connect(lambda text: self._save_config_value(self.CONFIG_KEY_LIMIT_START_TIME, text))
    start_time_layout.addWidget(self.start_time_entry)
    start_time_layout.addStretch()
    time_limit_v_layout.addLayout(start_time_layout)
    
    end_time_layout = QHBoxLayout()
    self.end_time_label = QLabel()
    end_time_layout.addWidget(self.end_time_label)
    self.end_time_entry = QLineEdit(self.limit_end_time_str)
    self.end_time_entry.setFixedWidth(120)
    self.end_time_entry.textChanged.connect(lambda text: self._save_config_value(self.CONFIG_KEY_LIMIT_END_TIME, text))
    end_time_layout.addWidget(self.end_time_entry)
    end_time_layout.addStretch()
    time_limit_v_layout.addLayout(end_time_layout)
    
    time_limit_v_layout.addStretch()
    self.time_limit_frame.setLayout(time_limit_v_layout)
    time_options_layout.addWidget(self.time_limit_frame)

    # --- Ajuste de Tempo ---
    self.offset_frame_process = QGroupBox()
    offset_v_layout = QVBoxLayout()

    self.offset_seconds_label_process = QLabel()
    offset_v_layout.addWidget(self.offset_seconds_label_process)

    self.offset_entry = QLineEdit(self.offset_seconds_var_val)
    self.offset_entry.setFixedWidth(120)
    offset_v_layout.addWidget(self.offset_entry)

    self.btn_apply_offset_process = QPushButton()
    self.btn_apply_offset_process.setObjectName("btn_apply_offset_srt")
    self.btn_apply_offset_process.clicked.connect(self.apply_time_offset_and_save_srt)
    
    btn_offset_layout = QHBoxLayout()
    btn_offset_layout.addWidget(self.btn_apply_offset_process)
    btn_offset_layout.addStretch()
    offset_v_layout.addLayout(btn_offset_layout)
    
    offset_v_layout.addStretch()
    self.offset_frame_process.setLayout(offset_v_layout)
    time_options_layout.addWidget(self.offset_frame_process)

    layout.addLayout(time_options_layout)

    # --- Corte Único ---
    single_clip_h_layout = QHBoxLayout()
    self.single_clip_frame = QGroupBox()
    single_clip_layout = QVBoxLayout()
    
    clip_time_grid = QGridLayout()
    clip_time_grid.setColumnStretch(2, 1)
    clip_start_label = QLabel()
    self.single_clip_start_entry = QLineEdit("00:00:00")
    self.single_clip_start_entry.setFixedWidth(120)
    clip_end_label = QLabel()
    self.single_clip_end_entry = QLineEdit("00:00:00")
    self.single_clip_end_entry.setFixedWidth(120)
    clip_time_grid.addWidget(clip_start_label, 0, 0)
    clip_time_grid.addWidget(self.single_clip_start_entry, 0, 1)
    clip_time_grid.addWidget(clip_end_label, 1, 0)
    clip_time_grid.addWidget(self.single_clip_end_entry, 1, 1)
    
    self.single_clip_start_label = clip_start_label
    self.single_clip_end_label = clip_end_label

    single_clip_layout.addLayout(clip_time_grid)

    self.btn_single_clip = QPushButton()
    self.btn_single_clip.clicked.connect(self.start_single_clip_process)
    
    btn_clip_layout = QHBoxLayout()
    btn_clip_layout.addWidget(self.btn_single_clip)
    btn_clip_layout.addStretch()
    single_clip_layout.addLayout(btn_clip_layout)

    single_clip_layout.addStretch()
    self.single_clip_frame.setLayout(single_clip_layout)
    single_clip_h_layout.addWidget(self.single_clip_frame)
    single_clip_h_layout.addStretch()
    layout.addLayout(single_clip_h_layout)

    layout.addStretch()