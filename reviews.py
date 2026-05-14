# reviews.py

from aqt.qt import (
    QHBoxLayout, QVBoxLayout, QGroupBox,
    QPushButton, QListWidget, QListWidgetItem,
    QTextEdit, QLabel, QSlider, QComboBox,
    QStyle, QMenu, Qt, QCheckBox
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

def setup_preview_tab(self):
    layout = QHBoxLayout(self.tab_preview)

    # Left side: File list
    left_panel = QVBoxLayout()
    left_panel.setSpacing(10)
    
    self.preview_file_list_group = QGroupBox()
    file_list_layout = QVBoxLayout()
    
    preview_buttons_layout = QHBoxLayout()
    self.preview_refresh_button = QPushButton()
    self.preview_refresh_button.clicked.connect(self.populate_preview_list)
    preview_buttons_layout.addWidget(self.preview_refresh_button)

    self.preview_clear_all_button = QPushButton()
    self.preview_clear_all_button.clicked.connect(self.clear_all_generated_files)
    preview_buttons_layout.addWidget(self.preview_clear_all_button)
    file_list_layout.addLayout(preview_buttons_layout)

    self.preview_list_widget = QListWidget()
    self.preview_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
    self.preview_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.preview_list_widget.customContextMenuRequested.connect(self.show_preview_context_menu)
    self.preview_list_widget.currentItemChanged.connect(self.on_preview_item_selected)
    file_list_layout.addWidget(self.preview_list_widget)
    
    self.preview_file_list_group.setLayout(file_list_layout)
    left_panel.addWidget(self.preview_file_list_group)
    
    layout.addLayout(left_panel, 1) # Stretch factor 1

    # Right side: Player and subtitle
    right_panel = QVBoxLayout()
    self.preview_player_group = QGroupBox()
    player_layout = QVBoxLayout()

    # Media Player setup
    self.video_widget = QVideoWidget()
    self.media_player = QMediaPlayer()
    self.media_player.setVideoOutput(self.video_widget)
    player_layout.addWidget(self.video_widget)

    # Controls Layout
    controls_layout = QHBoxLayout()
    
    self.play_pause_button = QPushButton()
    self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
    self.play_pause_button.clicked.connect(self.toggle_playback)
    controls_layout.addWidget(self.play_pause_button)

    self.speed_combo = QComboBox()
    self.speed_combo.addItems(["0.5x", "1x (Normal)", "1.5x", "2x"])
    self.speed_combo.currentIndexChanged.connect(self.change_playback_speed)
    controls_layout.addWidget(self.speed_combo)

    self.volume_slider = QSlider(Qt.Orientation.Horizontal)
    self.volume_slider.setRange(0, 100)
    self.volume_slider.valueChanged.connect(self.set_volume)
    controls_layout.addWidget(self.volume_slider)

    player_layout.addLayout(controls_layout)

    # Subtitle Area
    subtitle_header_layout = QHBoxLayout()
    self.subtitle_preview_label = QLabel()
    subtitle_header_layout.addWidget(self.subtitle_preview_label)
    subtitle_header_layout.addStretch()
    self.show_translation_cb = QCheckBox()
    self.show_translation_cb.stateChanged.connect(self.on_preview_item_selected_refresh)
    subtitle_header_layout.addWidget(self.show_translation_cb)
    player_layout.addLayout(subtitle_header_layout)

    self.subtitle_preview_area = QTextEdit()
    self.subtitle_preview_area.setReadOnly(True)
    self.subtitle_preview_area.setMaximumHeight(100)
    player_layout.addWidget(self.subtitle_preview_area)
    
    self.preview_player_group.setLayout(player_layout)
    right_panel.addWidget(self.preview_player_group)
    
    layout.addLayout(right_panel, 2) # Stretch factor 2 (wider)

    # Connect player signals
    self.media_player.playbackStateChanged.connect(self.update_play_button_state)
    self.media_player.mediaStatusChanged.connect(self.handle_media_status_changed)