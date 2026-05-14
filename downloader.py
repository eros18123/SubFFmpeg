# downloader.py

import os
import re
import json
import subprocess
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
            ytdlp_path = os.path.join(self.addon_path, "yt-dlp.exe")
            if not os.path.exists(ytdlp_path):
                self.signals.error.emit("Erro: yt-dlp.exe não encontrado na pasta do addon.")
                return

            command = [ytdlp_path, "-j", "--no-playlist", self.url]
            if self.use_cookies and self.cookie_file:
                command.extend(["--cookies", self.cookie_file])

            proc = subprocess.run(
                command, capture_output=True, text=True, encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if proc.returncode != 0:
                self.signals.error.emit(f"yt-dlp falhou:\n{proc.stderr}")
                return
            
            video_info = json.loads(proc.stdout)
            video_formats =[]
            
            for f in video_info.get('formats',[]):
                if f.get('vcodec') not in [None, 'none']:
                    video_formats.append({
                        'format_id': f['format_id'],
                        'resolution': f.get('resolution'),
                        'height': f.get('height'),
                        'filesize_pretty': self.format_bytes(f.get('filesize') or f.get('filesize_approx')),
                        'fps': f.get('fps'),
                        'has_audio': f.get('acodec') not in [None, 'none']
                    })

            video_formats.sort(key=lambda x: (x.get('height') or 0, x.get('fps') or 0), reverse=True)
            
            unique_video_formats = {}
            for f in video_formats:
                res_key = f.get('resolution') or f"Altura-{f.get('height')}"
                if res_key not in unique_video_formats:
                    unique_video_formats[res_key] = f
            
            self.signals.finished.emit({'video': list(unique_video_formats.values())})
        except Exception as e:
            self.signals.error.emit(f"Erro inesperado ao buscar formatos:\n{e}")

    def format_bytes(self, size: int) -> str:
        if size is None: return "N/A"
        power = 1024; n = 0
        power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G'}
        while size > power and n < len(power_labels) - 1:
            size /= power; n += 1
        return f"{size:.1f} {power_labels[n]}B"

class DownloadQueueWorker(QObject):
    progress = pyqtSignal(int, int)
    status_update = pyqtSignal(int, str)
    finished_item = pyqtSignal(int, bool, str)
    queue_finished = pyqtSignal()

    def __init__(self, addon_path: str):
        super().__init__()
        self.addon_path = addon_path
        self.queue =[]
        self.is_running = False
        self.process = None
        self.current_task = None

    def start(self, queue: List[Dict]):
        if self.is_running:
            return
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
        
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        
        self.process.readyRead.connect(lambda: self._handle_output(row))
        self.process.finished.connect(lambda exit_code, status: self._on_item_finished(row, exit_code))

        # Pega o caminho do FFmpeg do addon principal
        from .__init__ import _FFMPEG_PATH
        ffmpeg_path_str = str(_FFMPEG_PATH) if _FFMPEG_PATH else "ffmpeg"
        ytdlp_path = os.path.join(self.addon_path, "yt-dlp.exe")
        
        command = [ytdlp_path, "--ffmpeg-location", ffmpeg_path_str]
        
        if task.get('use_cookies') and task.get('cookie_file'):
            command.extend(["--cookies", task['cookie_file']])
        
        if task.get('is_sub_task'):
            command.extend(["--skip-download"])
            command.extend([
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", task.get('subs_langs', 'pt'),
                "--sub-format", "vtt/srt/best",
                "--convert-subs", "srt"
            ])
        else:
            if task['is_audio']:
                command.extend(["-f", "bestaudio", "-x", "--audio-format", "mp3", "--audio-quality", "0"])
            else:
                if task.get('has_audio'):
                    command.extend(["-f", task['format_id']])
                else:
                    command.extend(["-f", f"{task['format_id']}+bestaudio/best"])
                command.extend(["--merge-output-format", "mp4", "--remux-video", "mp4"])
        
        command.extend(["-P", task['save_path'], "--newline", "--no-playlist", task['url']])
        
        self.process.start(command[0], command[1:])

    def _handle_output(self, row: int):
        output = self.process.readAll().data().decode('utf-8', errors='ignore')
        
        match = re.search(r"\[download\]\s+([0-9.]+)%", output)
        if match:
            self.progress.emit(row, int(float(match.group(1))))
            
        if "[Merger]" in output or "[VideoRemuxer]" in output or "[ffmpeg]" in output:
            self.status_update.emit(row, "Processando (FFmpeg)...")
        elif "[info] Writing video subtitles" in output:
            self.status_update.emit(row, "Baixando Legendas...")

    def _on_item_finished(self, row: int, exit_code: int):
        success = (exit_code == 0)
        task = self.current_task
        
        if task.get('is_sub_task'):
            if success:
                message = "Concluído (Vídeo e Legenda)"
            else:
                message = "Concluído (Vídeo salvo, sem legenda)"
                success = True 
        else:
            if success:
                has_sub_task = any(t.get('row') == row and t.get('is_sub_task') for t in self.queue)
                if has_sub_task:
                    message = "Processando Legendas..."
                else:
                    message = "Concluído"
            else:
                message = "Erro no Vídeo"
                self.queue =[t for t in self.queue if not (t.get('row') == row and t.get('is_sub_task'))]
        
        self.finished_item.emit(row, success, message)
        self._process_next_item()

# --- Funções de UI e Callbacks ---

def setup_downloader_tab(dialog):
    layout = QVBoxLayout(dialog.tab_downloader)
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    layout.addWidget(scroll_area)
    
    container_widget = QWidget()
    scroll_area.setWidget(container_widget)
    main_layout = QVBoxLayout(container_widget)

    # 1. URL
    url_group = QGroupBox("1. Insira a URL (YouTube, Facebook, Instagram, TikTok, Pornhub, Xvideos, etc.)")
    url_layout = QHBoxLayout()
    dialog.dl_url_input = QLineEdit()
    dialog.dl_url_input.setPlaceholderText("Cole a URL da mídia aqui")
    dialog.dl_analyze_button = QPushButton("Analisar Link")
    dialog.dl_analyze_button.clicked.connect(lambda: dl_fetch_formats(dialog))
    url_layout.addWidget(dialog.dl_url_input)
    url_layout.addWidget(dialog.dl_analyze_button)
    url_group.setLayout(url_layout)
    main_layout.addWidget(url_group)

    # 2. ONDE SALVAR
    save_group = QGroupBox("2. Escolha Onde Salvar")
    save_layout = QVBoxLayout()
    dialog.dl_desktop_radio = QRadioButton("Salvar na Área de Trabalho")
    dialog.dl_desktop_radio.setChecked(True)
    dialog.dl_custom_path_radio = QRadioButton("Escolher outro local...")
    custom_path_widget = QWidget()
    custom_path_layout = QHBoxLayout(custom_path_widget)
    custom_path_layout.setContentsMargins(20, 0, 0, 0)
    dialog.dl_custom_path_display = QLineEdit()
    dialog.dl_custom_path_display.setReadOnly(True)
    dialog.dl_custom_path_display.setPlaceholderText("Nenhum local selecionado")
    dialog.dl_browse_button = QPushButton("Procurar...")
    dialog.dl_browse_button.clicked.connect(lambda: dl_select_custom_path(dialog))
    custom_path_layout.addWidget(dialog.dl_custom_path_display)
    custom_path_layout.addWidget(dialog.dl_browse_button)
    save_layout.addWidget(dialog.dl_desktop_radio)
    save_layout.addWidget(dialog.dl_custom_path_radio)
    save_layout.addWidget(custom_path_widget)
    save_group.setLayout(save_layout)
    main_layout.addWidget(save_group)
    dialog.dl_custom_path_radio.toggled.connect(custom_path_widget.setEnabled)
    custom_path_widget.setEnabled(False)

    # 3. AUTENTICAÇÃO
    auth_group = QGroupBox("3. Autenticação (para sites que exigem login)")
    auth_layout = QVBoxLayout()
    dialog.dl_no_auth_radio = QRadioButton("Nenhuma (padrão)")
    dialog.dl_no_auth_radio.setChecked(True)
    dialog.dl_cookie_file_radio = QRadioButton("Usar arquivo de cookies (.txt)")
    cookie_file_widget = QWidget()
    cookie_file_layout = QVBoxLayout(cookie_file_widget)
    cookie_file_layout.setContentsMargins(20, 0, 0, 0)
    cookie_browse_layout = QHBoxLayout()
    dialog.dl_cookie_file_display = QLineEdit()
    dialog.dl_cookie_file_display.setReadOnly(True)
    dialog.dl_cookie_file_display.setPlaceholderText("Nenhum arquivo selecionado")
    dialog.dl_browse_cookie_button = QPushButton("Procurar...")
    dialog.dl_browse_cookie_button.clicked.connect(lambda: dl_select_cookie_file(dialog))
    cookie_browse_layout.addWidget(dialog.dl_cookie_file_display)
    cookie_browse_layout.addWidget(dialog.dl_browse_cookie_button)
    
    from .__init__ import addon_path
    icon_path = os.path.join(addon_path, "export_icon.png").replace('\\', '/')
    cookie_help_label = QLabel(f"<b>Como obter o arquivo de cookies:</b><br>1. Instale a extensão <b>'Cookie-Editor'</b> no Chrome/Firefox.<br>2. No navegador, <b>faça login no site</b> (ex: TikTok).<br>3. Com o site aberto, clique no ícone da extensão (🍪).<br>4. No popup, clique em <b>'Export'</b> <img src='{icon_path}' style='vertical-align: middle; height: 16px;'>.<br>5. Abra o Bloco de Notas, cole o texto e salve como um arquivo .txt.")
    cookie_help_label.setWordWrap(True)
    cookie_file_layout.addLayout(cookie_browse_layout)
    cookie_file_layout.addWidget(cookie_help_label)
    auth_layout.addWidget(dialog.dl_no_auth_radio)
    auth_layout.addWidget(dialog.dl_cookie_file_radio)
    auth_layout.addWidget(cookie_file_widget)
    dialog.dl_cookie_file_radio.toggled.connect(cookie_file_widget.setVisible)
    cookie_file_widget.setVisible(False)
    auth_group.setLayout(auth_layout)
    main_layout.addWidget(auth_group)

    # 4. FORMATO E OPÇÕES
    format_group = QGroupBox("4. Escolha o Formato e Opções")
    format_layout = QVBoxLayout()
    
    subs_layout = QHBoxLayout()
    dialog.dl_download_subs_checkbox = QCheckBox("Baixar legendas (.srt) junto com o vídeo")
    dialog.dl_download_subs_checkbox.setChecked(False)
    
    dialog.dl_subs_langs_input = QLineEdit("pt")
    dialog.dl_subs_langs_input.setPlaceholderText("Ex: pt ou pt-BR")
    dialog.dl_subs_langs_input.setToolTip("Use 'pt' para Português. Se o vídeo tiver legenda em PT-BR, digite 'pt-BR'.")
    dialog.dl_subs_langs_input.setEnabled(False)
    
    dialog.dl_download_subs_checkbox.toggled.connect(dialog.dl_subs_langs_input.setEnabled)
    
    subs_layout.addWidget(dialog.dl_download_subs_checkbox)
    subs_layout.addWidget(QLabel("Idiomas:"))
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
    
    dialog.dl_tabs.addTab(dialog.dl_video_tab, "Vídeo (MP4)")
    dialog.dl_tabs.addTab(dialog.dl_audio_tab, "Áudio (MP3)")
    format_layout.addWidget(dialog.dl_tabs)
    format_group.setLayout(format_layout)
    main_layout.addWidget(format_group)

    # 5. FILA DE DOWNLOADS
    queue_group = QGroupBox("5. Fila de Downloads")
    queue_layout = QVBoxLayout()
    dialog.dl_queue_table = QTableWidget()
    dialog.dl_queue_table.setColumnCount(3)
    dialog.dl_queue_table.setHorizontalHeaderLabels(["URL", "Status", "Progresso"])
    dialog.dl_queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    dialog.dl_queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    dialog.dl_queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    queue_layout.addWidget(dialog.dl_queue_table)
    
    queue_buttons_layout = QHBoxLayout()
    dialog.dl_start_queue_button = QPushButton("Iniciar Fila")
    dialog.dl_start_queue_button.setEnabled(False)
    dialog.dl_clear_completed_button = QPushButton("Limpar Concluídos")
    queue_buttons_layout.addWidget(dialog.dl_start_queue_button)
    queue_buttons_layout.addWidget(dialog.dl_clear_completed_button)
    queue_layout.addLayout(queue_buttons_layout)
    
    queue_group.setLayout(queue_layout)
    main_layout.addWidget(queue_group)
    
    dialog.dl_start_queue_button.clicked.connect(lambda: dl_start_queue(dialog))
    dialog.dl_clear_completed_button.clicked.connect(lambda: dl_clear_completed(dialog))

    # Inicialização de variáveis
    dialog.dl_url = ""
    dialog.dl_custom_save_path = ""
    dialog.dl_cookie_file_path = ""
    dialog.dl_download_queue =[]
    
    dialog.dl_worker = DownloadQueueWorker(str(addon_path))
    dialog.dl_worker_thread = QThread()
    dialog.dl_worker.moveToThread(dialog.dl_worker_thread)
    dialog.dl_worker_thread.start()

    dialog.dl_worker.progress.connect(lambda r, p: dl_update_progress_bar(dialog, r, p))
    dialog.dl_worker.status_update.connect(lambda r, t: dl_update_status_text(dialog, r, t))
    dialog.dl_worker.finished_item.connect(lambda r, s, m: dl_update_status_on_finish(dialog, r, s, m))
    dialog.dl_worker.queue_finished.connect(lambda: dl_on_queue_finished(dialog))

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
    url = dialog.dl_url_input.text()
    if not url:
        showWarning("Por favor, insira uma URL.")
        return
    dialog.dl_url = url
    
    use_cookies = dialog.dl_cookie_file_radio.isChecked()
    cookie_file = dialog.dl_cookie_file_path
    if use_cookies and not cookie_file:
        showWarning("Por favor, selecione um arquivo de cookies ou desative a opção.")
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
        dialog.dl_video_layout.itemAt(i).widget().setParent(None)
    for i in reversed(range(dialog.dl_audio_layout.count())):
        dialog.dl_audio_layout.itemAt(i).widget().setParent(None)

def dl_on_formats_ready(dialog, formats: Dict):
    dialog.dl_analyze_button.setText("Analisar Link")
    dialog.dl_analyze_button.setEnabled(True)
    video_formats = formats.get('video',[])
    if video_formats:
        dialog.dl_video_layout.addWidget(QLabel("<b>Resolução</b>"), 0, 0)
        dialog.dl_video_layout.addWidget(QLabel("<b>Tamanho</b>"), 0, 1)
        dialog.dl_video_layout.addWidget(QLabel("<b>Ação</b>"), 0, 2)
        for i, f in enumerate(video_formats):
            label_res = f"{f['resolution']} @{f['fps']}fps" if f.get('fps') else f['resolution']
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
    save_path = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop') if dialog.dl_desktop_radio.isChecked() else dialog.dl_custom_save_path
    if not save_path:
        showWarning("Por favor, selecione um local para salvar.")
        return
    
    use_cookies = dialog.dl_cookie_file_radio.isChecked()
    cookie_file = dialog.dl_cookie_file_path
    if use_cookies and not cookie_file:
        showWarning("Por favor, selecione um arquivo de cookies ou desative a opção.")
        return

    row_position = dialog.dl_queue_table.rowCount()
    
    task_video = {
        'url': url, 'format_id': format_id, 'is_audio': is_audio, 'has_audio': has_audio,
        'save_path': save_path, 'use_cookies': use_cookies, 'cookie_file': cookie_file,
        'row': row_position,
        'is_sub_task': False
    }
    dialog.dl_download_queue.append(task_video)

    if dialog.dl_download_subs_checkbox.isChecked() and not is_audio:
        task_subs = {
            'url': url, 'format_id': format_id, 'is_audio': is_audio, 'has_audio': has_audio,
            'save_path': save_path, 'use_cookies': use_cookies, 'cookie_file': cookie_file,
            'subs_langs': dialog.dl_subs_langs_input.text().strip() or "pt",
            'row': row_position,
            'is_sub_task': True
        }
        dialog.dl_download_queue.append(task_subs)

    dialog.dl_queue_table.insertRow(row_position)
    dialog.dl_queue_table.setItem(row_position, 0, QTableWidgetItem(url))
    dialog.dl_queue_table.setItem(row_position, 1, QTableWidgetItem("Pendente"))
    
    progress_bar = QProgressBar()
    progress_bar.setValue(0)
    dialog.dl_queue_table.setCellWidget(row_position, 2, progress_bar)
    
    dialog.dl_start_queue_button.setEnabled(True)
    tooltip(f"Adicionado à fila: {os.path.basename(url)}")

def dl_start_queue(dialog):
    if not dialog.dl_download_queue:
        showInfo("A fila de downloads está vazia.")
        return
    
    dialog.dl_start_queue_button.setEnabled(False)
    dialog.dl_analyze_button.setEnabled(False)
    dialog.dl_worker.start(dialog.dl_download_queue)
    dialog.dl_download_queue =[]

def dl_update_progress_bar(dialog, row, percentage):
    progress_bar = dialog.dl_queue_table.cellWidget(row, 2)
    if progress_bar:
        progress_bar.setValue(percentage)
    
    status_item = dialog.dl_queue_table.item(row, 1)
    if status_item and status_item.text() == "Pendente":
        status_item.setText("Baixando...")

def dl_update_status_text(dialog, row, text):
    status_item = dialog.dl_queue_table.item(row, 1)
    if status_item and "Concluído" not in status_item.text() and "Erro" not in status_item.text():
        status_item.setText(text)

def dl_update_status_on_finish(dialog, row, success, message):
    status_item = dialog.dl_queue_table.item(row, 1)
    if status_item:
        status_item.setText(message)
        status_item.setForeground(Qt.GlobalColor.green if success else Qt.GlobalColor.red)

def dl_on_queue_finished(dialog):
    tooltip("Todos os downloads foram concluídos.")
    dialog.dl_start_queue_button.setEnabled(False)
    dialog.dl_analyze_button.setEnabled(True)

def dl_clear_completed(dialog):
    for row in range(dialog.dl_queue_table.rowCount() - 1, -1, -1):
        status_item = dialog.dl_queue_table.item(row, 1)
        if status_item and ("Concluído" in status_item.text() or "Erro" in status_item.text()):
            dialog.dl_queue_table.removeRow(row)

def dl_on_fetch_error(dialog, error_msg: str):
    dialog.dl_analyze_button.setText("Analisar Link")
    dialog.dl_analyze_button.setEnabled(True)

    is_tiktok_login_error = "tiktok is requiring login" in error_msg.lower()
    is_unsupported_url_error = "unsupported url" in error_msg.lower()

    if is_tiktok_login_error and dialog.dl_no_auth_radio.isChecked():
        dl_show_tiktok_auth_instructions(dialog)
    elif is_unsupported_url_error and "novinhabucetuda.com" in dialog.dl_url:
        dl_handle_unsupported_url(dialog, dialog.dl_url)
    else:
        showWarning(error_msg)

def dl_handle_unsupported_url(dialog, original_url: str):
        tooltip("URL não suportada. Tentando encontrar vídeo embutido...")
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            
            response = requests.get(original_url, headers=headers, timeout=15)
            response.raise_for_status()
            html_content = response.text
            
            iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', html_content)
            if not iframe_match:
                showWarning("Não foi possível encontrar um vídeo embutido (iframe) nesta página.")
                return

            iframe_url = iframe_match.group(1)
            tooltip(f"Vídeo embutido encontrado. Analisando: {iframe_url}")

            response = requests.get(iframe_url, headers=headers, timeout=15)
            response.raise_for_status()
            iframe_content = response.text

            m3u8_match = re.search(r'["\'](https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*?)["\']', iframe_content)
            if m3u8_match:
                final_url = m3u8_match.group(1)
                showInfo(f"Link de vídeo final extraído com sucesso!\n\nTentando analisar:\n{final_url}")
                
                dialog.dl_url_input.setText(final_url)
                dl_fetch_formats(dialog)
            else:
                showWarning("Não foi possível extrair o link final do vídeo (.m3u8) da página embutida.")

        except Exception as e:
            showWarning(f"Falha ao tentar analisar a página para encontrar o vídeo embutido:\n{e}")

def dl_show_tiktok_auth_instructions(dialog):
    from .__init__ import addon_path
    icon_path = os.path.join(addon_path, "export_icon.png").replace('\\', '/')

    title = "Acesso ao TikTok Requer Login"
    instructions = f"""
    <p>O TikTok exige que você esteja logado para ver este conteúdo.</p>
    <p>Para resolver isso, você precisa fornecer os "cookies" do seu navegador para o add-on. Siga os passos abaixo:</p>
    
    <h4>Passo a Passo:</h4>
    <ol>
        <li><b>Instale a Extensão:</b> No seu navegador (Chrome, Firefox, etc.), instale a extensão chamada <b>"Cookie-Editor"</b>.</li>
        <li><b>Faça Login no TikTok:</b> Abra uma aba no seu navegador, acesse <a href="https://www.tiktok.com">tiktok.com</a> e faça login na sua conta.</li>
        <li><b>Abra a Extensão:</b> Com a página do TikTok aberta, clique no ícone da extensão "Cookie-Editor" (geralmente um biscoito 🍪).</li>
        
        <li><b>Exporte os Cookies:</b> No menu que aparecer, clique no botão <b>Export</b> <img src="{icon_path}" style="vertical-align: middle; height: 20px;">. Isso copiará os dados dos cookies automaticamente.</li>

        <li><b>Salve o Arquivo:</b> Abra um editor de texto (como o <b>Bloco de Notas</b>), <b>cole</b> o conteúdo que foi copiado e salve o arquivo. Dê um nome qualquer, como por exemplo <b>"cookies_tiktok.txt"</b>.</li>
        
        <li><b>Use no Add-on:</b>
            <ul>
                <li>Volte para esta janela do baixador.</li>
                <li>Na seção "3. Autenticação", marque a opção <b>"Usar arquivo de cookies (.txt)"</b>.</li>
                <li>Clique em "Procurar..." e selecione o arquivo <b>.txt</b> que você acabou de salvar.</li>
            </ul>
        </li>
        <li><b>Tente Novamente:</b> Com o arquivo de cookies selecionado, clique em <b>"Analisar Link"</b> novamente.</li>
    </ol>
    """
    msg_box = QMessageBox(dialog)
    msg_box.setIcon(QMessageBox.Icon.Information)
    msg_box.setWindowTitle(title)
    msg_box.setTextFormat(Qt.TextFormat.RichText)
    msg_box.setText(instructions)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg_box.exec()