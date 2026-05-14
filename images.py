# images.py

from aqt.qt import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QProgressBar,
    QCheckBox, QTextEdit
)

def setup_images_tab(self):
    layout = QVBoxLayout(self.tab_images)
    self.images_frame = QGroupBox()
    images_main_layout = QVBoxLayout()

    # --- NOVO: Geração a partir do vídeo de origem ---
    source_generation_group = QGroupBox()
    source_generation_layout = QVBoxLayout()

    self.images_from_source_info_label = QLabel()
    self.images_from_source_info_label.setWordWrap(True)
    source_generation_layout.addWidget(self.images_from_source_info_label)

    self.generate_from_source_button = QPushButton()
    self.generate_from_source_button.clicked.connect(self.start_image_generation_from_source)
    
    source_btn_layout = QHBoxLayout()
    source_btn_layout.addWidget(self.generate_from_source_button)
    source_btn_layout.addStretch()
    source_generation_layout.addLayout(source_btn_layout)
    
    source_generation_group.setLayout(source_generation_layout)
    images_main_layout.addWidget(source_generation_group)
    # --- FIM NOVO ---

    # --- Geração a partir dos vídeos já divididos ---
    split_generation_group = QGroupBox()
    split_generation_layout = QVBoxLayout()

    self.images_tab_info_text_label = QLabel()
    self.images_tab_info_text_label.setWordWrap(True)
    split_generation_layout.addWidget(self.images_tab_info_text_label)

    self.images_tab_output_path_label = QLabel()
    self.images_tab_output_path_label.setWordWrap(True)
    split_generation_layout.addWidget(self.images_tab_output_path_label)

    self.direct_to_media_collection_cb_images = QCheckBox()
    self.direct_to_media_collection_cb_images.setChecked(self.pref_direct_images_to_cm)
    self.direct_to_media_collection_cb_images.stateChanged.connect(self._on_direct_images_to_cm_changed)
    split_generation_layout.addWidget(self.direct_to_media_collection_cb_images)

    images_buttons_layout = QHBoxLayout()
    self.convert_videos_button = QPushButton()
    self.convert_videos_button.clicked.connect(self.start_video_to_image_conversion)
    images_buttons_layout.addWidget(self.convert_videos_button)
    images_buttons_layout.addStretch()
    split_generation_layout.addLayout(images_buttons_layout)
    
    split_generation_group.setLayout(split_generation_layout)
    images_main_layout.addWidget(split_generation_group)
    # --- FIM ---

    # --- Controles e Log (Comum a ambos os processos) ---
    self.stop_image_conversion_button = QPushButton()
    self.stop_image_conversion_button.clicked.connect(self.request_stop_image_conversion)
    self.stop_image_conversion_button.setEnabled(False)
    
    stop_btn_layout = QHBoxLayout()
    stop_btn_layout.addWidget(self.stop_image_conversion_button)
    stop_btn_layout.addStretch()
    images_main_layout.addLayout(stop_btn_layout)

    self.image_conversion_progress_bar = QProgressBar()
    self.image_conversion_progress_bar.setMaximum(100); self.image_conversion_progress_bar.setValue(0)
    images_main_layout.addWidget(self.image_conversion_progress_bar)

    self.image_conversion_progress_label = QLabel("0%")
    images_main_layout.addWidget(self.image_conversion_progress_label)

    self.image_conversion_status_label = QLabel()
    images_main_layout.addWidget(self.image_conversion_status_label)

    self.log_images_frame = QGroupBox()
    log_images_layout = QVBoxLayout()
    self.log_text_area_images = QTextEdit(); self.log_text_area_images.setReadOnly(True); self.log_text_area_images.setFixedHeight(100)
    log_images_layout.addWidget(self.log_text_area_images)
    self.log_images_frame.setLayout(log_images_layout)
    images_main_layout.addWidget(self.log_images_frame)

    self.images_frame.setLayout(images_main_layout)
    layout.addWidget(self.images_frame)
    layout.addStretch()