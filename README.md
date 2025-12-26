# Houdini + Python (hython) Material Sweep Demo

This project demonstrates a simple CG pipeline tool built with **Houdini** and **Python (hython)** to automate material parameter sweeps and batch rendering using the **Karma renderer**.

The goal is to showcase tool development and rendering workflow automation rather than artistic complexity.

---

## Overview

- Loads a Houdini `.hipnc` scene headlessly using `hython`
- Programmatically modifies a material parameter (surface roughness)
- Renders multiple outputs via Karma
- Writes images to disk with consistent naming

This type of workflow mirrors common tasks in production pipelines where tools are used to validate shading behavior or generate look-development variations.

---

## Tools & Technologies

- **Houdini 21 (Apprentice)**
- **Python (hython)**
- **Houdini `hou` Python API**
- **Karma Renderer**
- macOS

---

## How It Works

1. The script loads the Houdini scene:
   ```python
   hou.hipFile.load("scene.hipnc")

2. A range of roughness values is iterated over: roughness_values = [0.1, 0.3, 0.5, 0.7, 0.9]

---

## Running the Script

hython render_sweep.py

