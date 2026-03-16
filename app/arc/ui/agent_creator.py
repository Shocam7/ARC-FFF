"""
arc/ui/agent_creator.py
───────────────────────
AgentCreatorDialog
"""

import os
import json
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFormLayout, QMessageBox, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
import yaml
from pathlib import Path

from google import genai as gai
from google.genai import types as gtypes

from ..core.config import P, FONT_UI, get_personas

logger = logging.getLogger(__name__)

class AgentGenerationThread(QThread):
    finished_success = pyqtSignal(dict)
    finished_error = pyqtSignal(str)

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent)
        self.prompt = prompt

    def run(self):
        try:
            client = gai.Client()

            skill_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "agent_creation_skill.md")
            skill_text = ""
            try:
                with open(skill_path, "r", encoding="utf-8") as f:
                    skill_text = f.read()
            except Exception as e:
                logger.warning("Could not read agent_creation_skill.md: %s", e)

            system_inst = (
                "You are an expert persona designer for an AI panel conference.\n"
                "You must design a detailed, compelling persona based on the user's prompt.\n"
                "You MUST output raw JSON using the following exact keys:\n"
                "- id: a short slug containing ONLY letters, digits, and underscores (e.g. 'hacker_99', 'dr_null')\n"
                "- name: display name (e.g. 'Dr. Null', 'Captain Flint')\n"
                "- field: short academic/professional field (e.g. 'Cybersecurity', 'Pirate Economics')\n"
                "- instruction: the VERY DETAILED system prompt for this agent, including WHO YOU ARE, YOUR PERSONALITY, "
                "YOUR SPEECH PATTERNS, and YOUR ROLE IN THE PANEL. Use internet search to incorporate real-world grounded facts and contemporary context.\n"
                "- blob_colors: an array of EXACTLY 5 lists, where each list is [R, G, B, phase, speed, amplitude]. "
                "For example: [200, 50, 50, 0.0, 0.5, 1.0]. Choose 5 distinct colors matching the persona's vibe.\n"
                "Return only valid JSON. Do NOT wrap in markdown.\n\n"
                "IMPORTANT CAPABILITIES: Every agent has the following background capabilities that run independently:\n"
                "1. Google Search — use it whenever the user asks a factual question.\n"
                "2. Computer Use — use the trigger_computer_use tool when the user asks you to interact with a computer, open apps, browse websites, fill forms, or automate tasks.\n"
                "3. Image Generation — use the trigger_image_generation tool when the user asks you to create, generate, or draw an image.\n\n"
                "IMPORTANT BEHAVIOR RULES:\n"
                "- When you receive a [BACKGROUND UPDATE] message in your context, narrate it naturally and conversationally. Do NOT read it verbatim.\n"
                "- You can talk freely with the user WHILE Computer Use or Image Generation is running in the background.\n"
                "IMPORTANT STYLE RULE: Do NOT use special characters for formatting, such as ** (bold), * (italics), or any other complex markdown in the instruction text. Keep the text formatting very simple.\n\n"
                "--- RULES FOR AGENT CREATION ---\n"
            ) + skill_text

            config = gtypes.GenerateContentConfig(
                temperature=0.7,
                system_instruction=system_inst,
                tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
            )
            # Try applying thinking config for deeper reasoning if supported
            try:
                config.thinking_config = gtypes.ThinkingConfig(include_thoughts=True)
            except Exception:
                pass

            resp = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=self.prompt,
                config=config,
            )

            raw = resp.text.strip()
            if "```json" in raw:
                raw = raw.split("```json")[-1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[-1].split("```")[0].strip()

            persona_data = json.loads(raw)
            
            import re
            persona_data["id"] = re.sub(r"[^a-zA-Z0-9_]", "_", persona_data.get("id", "agent_1"))
            
            # Remove search grounding citations like [1] or [1, 2]
            if "instruction" in persona_data:
                persona_data["instruction"] = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", persona_data["instruction"])
            if "field" in persona_data:
                persona_data["field"] = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", persona_data["field"])

            # Format blob_colors properly as tuples
            new_blobs = []
            for b in persona_data.get("blob_colors", []):
                new_blobs.append(tuple(b))
            if len(new_blobs) != 5:
                # Provide fallbacks if LLM fails
                new_blobs = [
                    (0x9C, 0x27, 0xB0, 0.00,  0.50, 1.10),
                    (0xE9, 0x1E, 0x63, 2.82,  0.55, 1.00),
                    (0x67, 0x3A, 0xB7, 0.94,  0.40, 0.90),
                    (0xFF, 0x40, 0x81, 4.39,  0.50, 1.05),
                    (0x8E, 0x24, 0xAA, 5.65,  0.45, 0.90),
                ]
            persona_data["blob_colors"] = new_blobs
            persona_data["tile_label"] = f"{persona_data['name']}  ·  {persona_data['field']}"

            self.finished_success.emit(persona_data)
        except Exception as e:
            logger.exception("Failed to generate agent")
            self.finished_error.emit(str(e))

class AgentCreatorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create or Load Agent ✨")
        self.setFixedSize(500, 300)
        self.setStyleSheet(f"background: {P['surface']}; color: {P['text']};")

        self.result_persona = None

        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.saved_combo = QComboBox()
        self.saved_combo.setStyleSheet(f"background: {P['bg']}; color: {P['text']}; border: 1px solid {P['border']}; padding: 6px;")
        self.saved_combo.setFont(QFont(FONT_UI, 10))
        self.saved_combo.addItem("--- Create New Agent ---", None)
        self._load_saved_agents()
        self.saved_combo.currentIndexChanged.connect(self._on_saved_agent_changed)

        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("e.g. A cynical 90s AI hacker obsessed with zero-days")
        self.prompt_input.setStyleSheet(f"background: {P['bg']}; color: {P['text']}; border: 1px solid {P['border']}; padding: 8px; border-radius: 4px;")
        self.prompt_input.setFont(QFont(FONT_UI, 11))

        form.addRow("Saved Agents:", self.saved_combo)
        form.addRow("Agent Concept:", self.prompt_input)

        layout.addLayout(form)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_lbl = QLabel("")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet(f"color: {P['accent']}; font-weight: bold;")
        self.status_lbl.setFont(QFont(FONT_UI, 10))
        layout.addWidget(self.status_lbl)

        btn_layout = QHBoxLayout()
        self.create_btn = QPushButton("Create ✨")
        self.create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_btn.setStyleSheet(f"background: {P['agent_bub']}; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        self.create_btn.clicked.connect(self._on_create_or_load)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(f"background: {P['bg']}; padding: 8px 16px; border-radius: 4px;")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.create_btn)

        layout.addLayout(btn_layout)
        self.thread = None

    def _load_saved_agents(self):
        saved_dir = Path(__file__).resolve().parent.parent / "agents" / "saved_personas"
        if not saved_dir.exists():
            return
            
        for yaml_file in saved_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and "name" in data and "field" in data:
                        self.saved_combo.addItem(f"{data['name']} ({data['field']})", str(yaml_file))
            except Exception as e:
                logger.warning("Failed to load saved agent %s: %s", yaml_file, e)

    def _on_saved_agent_changed(self):
        is_new = self.saved_combo.currentData() is None
        self.prompt_input.setEnabled(is_new)
        self.create_btn.setText("Create ✨" if is_new else "Load 💾")
        if not is_new:
            self.prompt_input.setText("")

    def _on_create_or_load(self):
        saved_path = self.saved_combo.currentData()
        if saved_path:
            # Load selected agent
            self._load_from_disk(saved_path)
            return

        # Create new agent
        concept = self.prompt_input.text().strip()
        if not concept:
            QMessageBox.warning(self, "Input Error", "Please provide an agent concept.")
            return

        self.prompt_input.setEnabled(False)
        self.saved_combo.setEnabled(False)
        self.create_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status_lbl.setText("Thinking via Gemini + Google Search...")

        self.thread = AgentGenerationThread(concept, self)
        self.thread.finished_success.connect(self._on_success)
        self.thread.finished_error.connect(self._on_error)
        self.thread.start()

    def _load_from_disk(self, yaml_path_str: str):
        yaml_path = Path(yaml_path_str)
        md_path = yaml_path.with_suffix(".md")
        
        try:
            with open(yaml_path, "r", encoding="utf-8") as yf:
                persona_data = yaml.safe_load(yf)
                
            if md_path.exists():
                with open(md_path, "r", encoding="utf-8") as mf:
                    persona_data["instruction"] = mf.read()
                    
            if "blob_colors" in persona_data:
                 persona_data["blob_colors"] = [tuple(c) for c in persona_data["blob_colors"]]
                 
            self._on_success(persona_data)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load agent from disk:\n{e}")

    def _on_success(self, persona: dict):
        self.result_persona = persona
        self.accept()

    def _on_error(self, error: str):
        self.prompt_input.setEnabled(True)
        self.saved_combo.setEnabled(True)
        self.create_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status_lbl.setText("")
        QMessageBox.critical(self, "Generation Error", f"Failed to generate agent:\n{error}")
