
import os
import re
import json
import subprocess
import shutil
import base64
from typing import List, Dict
import requests

from aqt.qt import *
from aqt.utils import showWarning, showInfo, tooltip

class WorkerSignals(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

class FormatFetcherThread(QRunnable):
    def __init__(self, url: str, use_cookies: bool, cookie_file: str, addon_path: str):
        super().__init__()
        self.url = url
        self.use_cookies = use_cookies
        self.cookie_file = cookie_file
        self.addon_path = addon_path
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            ytdlp_path = os.path.join(self.addon_path, "yt-dlp.exe" if os.name == 'nt' else "yt-dlp")
            if not os.path.exists(ytdlp_path):
                self.signals.error.emit("yt-dlp não encontrado.")
                return

            target_url = self._extract_novinha_m3u8(self.url) if "novinhabucetuda.com" in self.url.lower() else self.url

            cmd = [
                ytdlp_path, "-j", "--no-playlist",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "--referer", "https://novinhabucetuda.com",
                target_url
            ]

            if self.use_cookies and self.cookie_file:
                cmd.extend(["--cookies", self.cookie_file])

            proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

            if proc.returncode != 0:
                self.signals.error.emit(f"yt-dlp falhou:\n{proc.stderr}")
                return

            video_info = json.loads(proc.stdout)
            video_formats = []

            for f in video_info.get('formats', []):
                if f.get('vcodec') not in [None, 'none']:
                    video_formats.append({
                        'format_id': f['format_id'],
                        'resolution': f.get('resolution') or f.get('height') or '1080p (HLS)',
                        'height': f.get('height') or 1080,
                        'filesize_pretty': self.format_bytes(f.get('filesize') or f.get('filesize_approx')),
                        'fps': f.get('fps'),
                        'has_audio': f.get('acodec') not in [None, 'none']
                    })

            if not video_formats:
                video_formats.append({
                    'format_id': 'best',
                    'resolution': '1080p (HLS)',
                    'height': 1080,
                    'filesize_pretty': 'Desconhecido',
                    'fps': None,
                    'has_audio': True
                })

            video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
            
            unique_video_formats = {}
            for f in video_formats:
                res_key = f.get('resolution') or f"Altura-{f.get('height')}"
                if res_key not in unique_video_formats:
                    unique_video_formats[res_key] = f

            self.signals.finished.emit({'video': list(unique_video_formats.values())})

        except Exception as e:
            self.signals.error.emit(f"Erro inesperado:\n{e}")

    def _extract_novinha_m3u8(self, page_url: str) -> str:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            r = requests.get(page_url, headers=headers, timeout=15)
            html = r.text

            b64_match = re.search(r'atob\(["\']([A-Za-z0-9+/=]+)["\']', html)
            if b64_match:
                try:
                    decoded = base64.b64decode(b64_match.group(1)).decode('utf-8')
                    if '.m3u8' in decoded:
                        return decoded
                except:
                    pass

            m3u8_match = re.search(r'["\'](https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*?)["\']', html)
            if m3u8_match:
                return m3u8_match.group(1)

            return page_url
        except:
            return page_url

    def format_bytes(self, size):
        if size is None: return "N/A"
        for unit in ['', 'K', 'M', 'G']:
            if size < 1024:
                return f"{size:.1f}{unit}B"
            size /= 1024
        return f"{size:.1f}TB"


class DownloadQueueWorker(QObject):
    progress = pyqtSignal(int, int)
    status_update = pyqtSignal(int, str)
    finished_item = pyqtSignal(int, bool, str)
    queue_finished = pyqtSignal()

    def __init__(self, addon_path: str):
        super().__init__()
        self.addon_path = addon_path
        self.queue = []
        self.is_running = False
        self.process = None
        self.current_task = None
        self.full_log = ""

    def start(self, queue: List[Dict]):
        if self.is_running: return
        self.queue = list(queue)
        self.is_running = True
        self._process_next_item()

    def stop(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
        self.is_running = False
        self.queue.clear()

    def _process_next_item(self):
        if not self.is_running or not self.queue:
            self.is_running = False
            self.queue_finished.emit()
            return

        self.current_task = self.queue.pop(0)
        task = self.current_task
        row = task['row']
        self.full_log = ""

        ffmpeg_path_str = os.path.join(self.addon_path, "ffmpeg_vendor", "ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
        if not os.path.exists(ffmpeg_path_str):
            ffmpeg_path_str = shutil.which("ffmpeg") or "ffmpeg"

        ytdlp_path = os.path.join(self.addon_path, "yt-dlp.exe" if os.name == 'nt' else "yt-dlp")

        url_to_use = self._extract_novinha_m3u8(task['url']) if "novinhabucetuda.com" in task['url'].lower() else task['url']

        command = [
            ytdlp_path,
            "--ffmpeg-location", ffmpeg_path_str,
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "--referer", "https://novinhabucetuda.com",
            "-P", task['save_path'],
            "--newline",
            "--no-playlist",
            url_to_use
        ]

        if task.get('use_cookies') and task.get('cookie_file'):
            command.extend(["--cookies", task['cookie_file']])

        if task.get('download_subs'):
            command.extend(["--write-subs", "--write-auto-subs", "--sub-langs", task['subs_langs'], "--convert-subs", "srt", "--embed-subs"])

        if task['is_audio']:
            command.extend(["-f", "bestaudio", "-x", "--audio-format", "mp3"])
        else:
            if task.get('has_audio'):
                command.extend(["-f", task['format_id']])
            else:
                command.extend(["-f", f"{task['format_id']}+bestaudio/best"])
            command.extend(["--recode-video", "mp4"])

        self.full_log += f"COMANDO:\n{' '.join(command)}\n\nSAÍDA:\n"

        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyRead.connect(lambda: self._handle_output(row))
        self.process.finished.connect(lambda code, _: self._on_item_finished(row, code))
        self.process.start(command[0], command[1:])

    def _extract_novinha_m3u8(self, page_url: str) -> str:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            r = requests.get(page_url, headers=headers, timeout=15)
            html = r.text

            b64_match = re.search(r'atob\(["\']([A-Za-z0-9+/=]+)["\']', html)
            if b64_match:
                try:
                    decoded = base64.b64decode(b64_match.group(1)).decode('utf-8')
                    if '.m3u8' in decoded:
                        return decoded
                except:
                    pass

            m3u8_match = re.search(r'["\'](https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*?)["\']', html)
            if m3u8_match:
                return m3u8_match.group(1)

            return page_url
        except:
            return page_url

    def _handle_output(self, row):
        output = self.process.readAll().data().decode('utf-8', errors='ignore')
        self.full_log += output
        m = re.search(r"\[download\]\s+([0-9.]+)%", output)
        if m:
            self.progress.emit(row, int(float(m.group(1))))

    def _on_item_finished(self, row, exit_code):
        success = exit_code == 0
        task = self.current_task
        message = "Concluído (com legenda)" if success and task.get('download_subs') else "Concluído" if success else "Erro no download"
        self.finished_item.emit(row, success, message)
        self._process_next_item()


def setup_downloader_tab(dialog):
    layout = QVBoxLayout(dialog.tab_downloader)
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    layout.addWidget(scroll_area)
    
    container_widget = QWidget()
    scroll_area.setWidget(container_widget)
    main_layout = QVBoxLayout(container_widget)

    dialog.dl_url_group = QGroupBox(dialog.tr("dl.group.url"))
    url_layout = QHBoxLayout()
    dialog.dl_url_input = QLineEdit()
    dialog.dl_url_input.setPlaceholderText(dialog.tr("dl.placeholder.url"))
    
    dialog.dl_analyze_button = QPushButton(dialog.tr("dl.button.analyze"))
    dialog.dl_analyze_button.clicked.connect(lambda: dl_fetch_formats(dialog))
    
    dialog.dl_update_button = QPushButton("Atualizar yt-dlp")
    dialog.dl_update_button.clicked.connect(lambda: dl_update_ytdlp(dialog))
    
    url_layout.addWidget(dialog.dl_url_input)
    url_layout.addWidget(dialog.dl_analyze_button)
    url_layout.addWidget(dialog.dl_update_button)
    dialog.dl_url_group.setLayout(url_layout)
    main_layout.addWidget(dialog.dl_url_group)

    dialog.dl_save_group = QGroupBox(dialog.tr("dl.group.save"))
    save_layout = QVBoxLayout()
    dialog.dl_desktop_radio = QRadioButton(dialog.tr("dl.radio.desktop"))
    dialog.dl_desktop_radio.setChecked(True)
    dialog.dl_custom_path_radio = QRadioButton(dialog.tr("dl.radio.custom_path"))
    custom_path_widget = QWidget()
    custom_path_layout = QHBoxLayout(custom_path_widget)
    custom_path_layout.setContentsMargins(20, 0, 0, 0)
    dialog.dl_custom_path_display = QLineEdit()
    dialog.dl_custom_path_display.setReadOnly(True)
    dialog.dl_custom_path_display.setPlaceholderText(dialog.tr("dl.placeholder.no_path"))
    dialog.dl_browse_button = QPushButton(dialog.tr("dl.button.browse"))
    dialog.dl_browse_button.clicked.connect(lambda: dl_select_custom_path(dialog))
    custom_path_layout.addWidget(dialog.dl_custom_path_display)
    custom_path_layout.addWidget(dialog.dl_browse_button)
    save_layout.addWidget(dialog.dl_desktop_radio)
    save_layout.addWidget(dialog.dl_custom_path_radio)
    save_layout.addWidget(custom_path_widget)
    dialog.dl_save_group.setLayout(save_layout)
    main_layout.addWidget(dialog.dl_save_group)
    dialog.dl_custom_path_radio.toggled.connect(custom_path_widget.setEnabled)
    custom_path_widget.setEnabled(False)

    dialog.dl_auth_group = QGroupBox(dialog.tr("dl.group.auth"))
    auth_layout = QVBoxLayout()
    dialog.dl_no_auth_radio = QRadioButton(dialog.tr("dl.radio.no_auth"))
    dialog.dl_no_auth_radio.setChecked(True)
    dialog.dl_cookie_file_radio = QRadioButton(dialog.tr("dl.radio.cookie"))
    cookie_file_widget = QWidget()
    cookie_file_layout = QVBoxLayout(cookie_file_widget)
    cookie_file_layout.setContentsMargins(20, 0, 0, 0)
    cookie_browse_layout = QHBoxLayout()
    dialog.dl_cookie_file_display = QLineEdit()
    dialog.dl_cookie_file_display.setReadOnly(True)
    dialog.dl_cookie_file_display.setPlaceholderText(dialog.tr("dl.placeholder.no_cookie"))
    dialog.dl_browse_cookie_button = QPushButton(dialog.tr("dl.button.browse"))
    dialog.dl_browse_cookie_button.clicked.connect(lambda: dl_select_cookie_file(dialog))
    cookie_browse_layout.addWidget(dialog.dl_cookie_file_display)
    cookie_browse_layout.addWidget(dialog.dl_browse_cookie_button)
    
    from .__init__ import addon_path
    icon_path = os.path.join(addon_path, "export_icon.png").replace('\\', '/')
    dialog.dl_cookie_help_label = QLabel(dialog.tr("dl.label.cookie_help", icon_path=icon_path))
    dialog.dl_cookie_help_label.setWordWrap(True)
    cookie_file_layout.addLayout(cookie_browse_layout)
    cookie_file_layout.addWidget(dialog.dl_cookie_help_label)
    auth_layout.addWidget(dialog.dl_no_auth_radio)
    auth_layout.addWidget(dialog.dl_cookie_file_radio)
    auth_layout.addWidget(cookie_file_widget)
    dialog.dl_cookie_file_radio.toggled.connect(cookie_file_widget.setVisible)
    cookie_file_widget.setVisible(False)
    dialog.dl_auth_group.setLayout(auth_layout)
    main_layout.addWidget(dialog.dl_auth_group)

    dialog.dl_format_group = QGroupBox(dialog.tr("dl.group.format"))
    format_layout = QVBoxLayout()
    
    subs_layout = QHBoxLayout()
    dialog.dl_download_subs_checkbox = QCheckBox(dialog.tr("dl.checkbox.subs"))
    dialog.dl_download_subs_checkbox.setChecked(False)
    
    dialog.dl_langs_label = QLabel(dialog.tr("dl.label.langs"))
    dialog.dl_subs_langs_input = QLineEdit()
    dialog.dl_subs_langs_input.setPlaceholderText(dialog.tr("dl.placeholder.langs"))
    dialog.dl_subs_langs_input.setEnabled(False)
    
    dialog.dl_download_subs_checkbox.toggled.connect(dialog.dl_subs_langs_input.setEnabled)
    
    subs_layout.addWidget(dialog.dl_download_subs_checkbox)
    subs_layout.addWidget(dialog.dl_langs_label)
    subs_layout.addWidget(dialog.dl_subs_langs_input)
    format_layout.addLayout(subs_layout)

    dialog.dl_tabs = QTabWidget()
    dialog.dl_video_tab = QWidget()
    video_tab_layout = QVBoxLayout(dialog.dl_video_tab)
    dialog.dl_video_layout = QGridLayout()
    video_tab_layout.addLayout(dialog.dl_video_layout)
    
    dialog.dl_audio_tab = QWidget()
    audio_tab_layout = QVBoxLayout(dialog.dl_audio_tab)
    dialog.dl_audio_layout = QGridLayout()
    audio_tab_layout.addLayout(dialog.dl_audio_layout)
    
    dialog.dl_tabs.addTab(dialog.dl_video_tab, dialog.tr("dl.tab.video"))
    dialog.dl_tabs.addTab(dialog.dl_audio_tab, dialog.tr("dl.tab.audio"))
    format_layout.addWidget(dialog.dl_tabs)
    dialog.dl_format_group.setLayout(format_layout)
    main_layout.addWidget(dialog.dl_format_group)

    dialog.dl_queue_group = QGroupBox(dialog.tr("dl.group.queue"))
    queue_layout = QVBoxLayout()
    dialog.dl_queue_table = QTableWidget()
    dialog.dl_queue_table.setColumnCount(3)
    dialog.dl_queue_table.setHorizontalHeaderLabels([dialog.tr("dl.table.url"), dialog.tr("dl.table.status"), dialog.tr("dl.table.progress")])
    dialog.dl_queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    dialog.dl_queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    dialog.dl_queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    queue_layout.addWidget(dialog.dl_queue_table)
    
    queue_buttons_layout = QHBoxLayout()
    dialog.dl_start_queue_button = QPushButton(dialog.tr("dl.button.start_queue"))
    dialog.dl_start_queue_button.setEnabled(False)
    dialog.dl_clear_completed_button = QPushButton(dialog.tr("dl.button.clear_completed"))
    queue_buttons_layout.addWidget(dialog.dl_start_queue_button)
    queue_buttons_layout.addWidget(dialog.dl_clear_completed_button)
    queue_layout.addLayout(queue_buttons_layout)
    
    dialog.dl_queue_group.setLayout(queue_layout)
    main_layout.addWidget(dialog.dl_queue_group)
    
    dialog.dl_start_queue_button.clicked.connect(lambda: dl_start_queue(dialog))
    dialog.dl_clear_completed_button.clicked.connect(lambda: dl_clear_completed(dialog))

    dialog.dl_url = ""
    dialog.dl_custom_save_path = ""
    dialog.dl_cookie_file_path = ""
    dialog.dl_download_queue = []
    
    from .__init__ import addon_path
    dialog.dl_worker = DownloadQueueWorker(str(addon_path))
    dialog.dl_worker_thread = QThread()
    dialog.dl_worker.moveToThread(dialog.dl_worker_thread)
    dialog.dl_worker_thread.start()

    dialog.dl_worker.progress.connect(lambda r, p: dl_update_progress_bar(dialog, r, p))
    dialog.dl_worker.status_update.connect(lambda r, t: dl_update_status_text(dialog, r, t))
    dialog.dl_worker.finished_item.connect(lambda r, s, m: dl_update_status_on_finish(dialog, r, s, m))
    dialog.dl_worker.queue_finished.connect(lambda: dl_on_queue_finished(dialog))


def dl_update_ytdlp(dialog):
    from .__init__ import addon_path
    ytdlp_path = os.path.join(addon_path, "yt-dlp.exe" if os.name == 'nt' else "yt-dlp")
    if not os.path.exists(ytdlp_path):
        showWarning("yt-dlp não encontrado.")
        return
    dialog.dl_update_button.setEnabled(False)
    dialog.dl_update_button.setText("Atualizando...")
    QApplication.processEvents()
    try:
        proc = subprocess.run([ytdlp_path, "-U"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if proc.returncode == 0:
            showInfo(f"yt-dlp atualizado!\n{proc.stdout}")
        else:
            showWarning(f"Falha:\n{proc.stderr}")
    except Exception as e:
        showWarning(str(e))
    finally:
        dialog.dl_update_button.setEnabled(True)
        dialog.dl_update_button.setText("Atualizar yt-dlp")


def dl_select_custom_path(dialog):
    path = QFileDialog.getExistingDirectory(dialog, "Selecione uma pasta para salvar")
    if path:
        dialog.dl_custom_save_path = path
        dialog.dl_custom_path_display.setText(path)

def dl_select_cookie_file(dialog):
    path, _ = QFileDialog.getOpenFileName(dialog, "Selecione o arquivo de cookies", "", "Arquivos de Texto (*.txt)")
    if path:
        dialog.dl_cookie_file_path = path
        dialog.dl_cookie_file_display.setText(path)

def dl_fetch_formats(dialog):
    url = dialog.dl_url_input.text().strip()
    if not url:
        showWarning("Por favor, insira uma URL.")
        return
    dialog.dl_url = url
    use_cookies = dialog.dl_cookie_file_radio.isChecked()
    cookie_file = dialog.dl_cookie_file_path
    if use_cookies and not cookie_file:
        showWarning("Selecione um arquivo de cookies ou desative a opção.")
        return

    dialog.dl_analyze_button.setText("Analisando...")
    dialog.dl_analyze_button.setEnabled(False)
    dl_clear_layouts(dialog)
    
    from .__init__ import addon_path
    worker = FormatFetcherThread(url, use_cookies, cookie_file, str(addon_path))
    worker.signals.finished.connect(lambda f: dl_on_formats_ready(dialog, f))
    worker.signals.error.connect(lambda e: dl_on_fetch_error(dialog, e))
    
    if not hasattr(dialog, 'dl_threadpool'):
        dialog.dl_threadpool = QThreadPool()
    dialog.dl_threadpool.start(worker)

def dl_clear_layouts(dialog):
    for i in reversed(range(dialog.dl_video_layout.count())):
        w = dialog.dl_video_layout.itemAt(i).widget()
        if w: w.setParent(None)
    for i in reversed(range(dialog.dl_audio_layout.count())):
        w = dialog.dl_audio_layout.itemAt(i).widget()
        if w: w.setParent(None)

def dl_on_formats_ready(dialog, formats: Dict):
    dialog.dl_analyze_button.setText(dialog.tr("dl.button.analyze"))
    dialog.dl_analyze_button.setEnabled(True)
    video_formats = formats.get('video', [])
    if video_formats:
        dialog.dl_video_layout.addWidget(QLabel("<b>Resolução</b>"), 0, 0)
        dialog.dl_video_layout.addWidget(QLabel("<b>Tamanho</b>"), 0, 1)
        dialog.dl_video_layout.addWidget(QLabel("<b>Ação</b>"), 0, 2)
        for i, f in enumerate(video_formats):
            label_res = f"{f['resolution']} @{f.get('fps')}fps" if f.get('fps') else str(f['resolution'])
            dialog.dl_video_layout.addWidget(QLabel(label_res), i + 1, 0)
            dialog.dl_video_layout.addWidget(QLabel(f['filesize_pretty']), i + 1, 1)
            btn = QPushButton("Adicionar à Fila")
            btn.clicked.connect(lambda _, u=dialog.dl_url, f_id=f['format_id'], has_a=f['has_audio']: dl_add_to_queue(dialog, u, f_id, False, has_a))
            dialog.dl_video_layout.addWidget(btn, i + 1, 2)
    else:
        dialog.dl_video_layout.addWidget(QLabel("Nenhum formato de vídeo encontrado."))
    
    dialog.dl_audio_layout.addWidget(QLabel("<b>Qualidade</b>"), 0, 0)
    dialog.dl_audio_layout.addWidget(QLabel("<b>Ação</b>"), 0, 1)
    mp3_btn = QPushButton("Adicionar à Fila")
    mp3_btn.clicked.connect(lambda _, u=dialog.dl_url: dl_add_to_queue(dialog, u, "mp3", True, False))
    dialog.dl_audio_layout.addWidget(mp3_btn, 1, 0, 1, 2)
    tooltip("Formatos carregados. Adicione à fila para baixar.")

def dl_add_to_queue(dialog, url, format_id, is_audio, has_audio=False):
    save_path = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop') if dialog.dl_desktop_radio.isChecked() else dialog.dl_custom_save_path
    if not save_path:
        showWarning("Selecione um local para salvar.")
        return
    use_cookies = dialog.dl_cookie_file_radio.isChecked()
    cookie_file = dialog.dl_cookie_file_path
    if use_cookies and not cookie_file:
        showWarning("Selecione um arquivo de cookies ou desative.")
        return

    row_position = dialog.dl_queue_table.rowCount()
    download_subs = dialog.dl_download_subs_checkbox.isChecked()
    user_langs = dialog.dl_subs_langs_input.text().strip()
    subs_langs = "pt*,en*" if not user_langs else f"{user_langs},{user_langs.split('-')[0]}*"
    
    task = {
        'url': url, 'format_id': format_id, 'is_audio': is_audio, 'has_audio': has_audio,
        'save_path': save_path, 'use_cookies': use_cookies, 'cookie_file': cookie_file,
        'row': row_position, 'download_subs': download_subs, 'subs_langs': subs_langs
    }
    dialog.dl_download_queue.append(task)

    dialog.dl_queue_table.insertRow(row_position)
    dialog.dl_queue_table.setItem(row_position, 0, QTableWidgetItem(url))
    dialog.dl_queue_table.setItem(row_position, 1, QTableWidgetItem("Pendente"))
    progress_bar = QProgressBar()
    progress_bar.setValue(0)
    dialog.dl_queue_table.setCellWidget(row_position, 2, progress_bar)
    
    dialog.dl_start_queue_button.setEnabled(True)
    tooltip("Adicionado à fila.")

def dl_start_queue(dialog):
    if not dialog.dl_download_queue:
        showInfo("Fila vazia.")
        return
    dialog.dl_start_queue_button.setEnabled(False)
    dialog.dl_analyze_button.setEnabled(False)
    dialog.dl_worker.start(dialog.dl_download_queue)
    dialog.dl_download_queue = []

def dl_update_progress_bar(dialog, row, percentage):
    pb = dialog.dl_queue_table.cellWidget(row, 2)
    if pb: pb.setValue(percentage)
    item = dialog.dl_queue_table.item(row, 1)
    if item and item.text() == "Pendente":
        item.setText("Baixando...")

def dl_update_status_text(dialog, row, text):
    item = dialog.dl_queue_table.item(row, 1)
    if item and "Concluído" not in item.text() and "Erro" not in item.text():
        item.setText(text)

def dl_update_status_on_finish(dialog, row, success, message):
    item = dialog.dl_queue_table.item(row, 1)
    if item:
        item.setText(message)
        item.setForeground(Qt.GlobalColor.green if success else Qt.GlobalColor.red)

def dl_on_queue_finished(dialog):
    tooltip("Downloads concluídos.")
    dialog.dl_start_queue_button.setEnabled(False)
    dialog.dl_analyze_button.setEnabled(True)

def dl_clear_completed(dialog):
    for row in range(dialog.dl_queue_table.rowCount() - 1, -1, -1):
        item = dialog.dl_queue_table.item(row, 1)
        if item and ("Concluído" in item.text() or "Erro" in item.text()):
            dialog.dl_queue_table.removeRow(row)

def dl_on_fetch_error(dialog, error_msg: str):
    dialog.dl_analyze_button.setText(dialog.tr("dl.button.analyze"))
    dialog.dl_analyze_button.setEnabled(True)
    showWarning(error_msg)

def dl_handle_unsupported_url(dialog, original_url: str):
    tooltip("Analisando página...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(original_url, headers=headers, timeout=15)
        html_content = response.text
        direct_url = None
        b64_match = re.search(r'atob\(["\']([A-Za-z0-9+/=]+)["\']', html_content)
        if b64_match:
            try:
                decoded = base64.b64decode(b64_match.group(1)).decode('utf-8')
                if '.m3u8' in decoded:
                    direct_url = decoded
            except:
                pass
        if not direct_url:
            m3u8_match = re.search(r'["\'](https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*?)["\']', html_content)
            if m3u8_match:
                direct_url = m3u8_match.group(1)
        if direct_url:
            dialog.dl_url_input.setText(direct_url)
            dl_fetch_formats(dialog)
        else:
            showWarning("Não foi possível extrair o link do vídeo.")
    except Exception as e:
        showWarning(str(e))
