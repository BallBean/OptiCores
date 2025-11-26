# OptiCores

Windows process optimizer & live dashboard (Python + customtkinter)

OptiCores เป็นแอปสำหรับ Windows ที่ช่วยจัดการและจูนประสิทธิภาพโปรเซสแบบ real-time  
เน้นใช้งานง่าย เห็นภาพ และมีตัวช่วยปรับแต่งแบบปลอดภัย

> **รองรับเฉพาะ Windows 10/11** และแนะนำให้รันในโหมด **Run as Administrator**  
> เพื่อให้ทุกฟีเจอร์ทำงานได้ครบ เช่น ปรับ Priority / Affinity / Power plan

---

## Features

- **Process Dashboard**
  - ตารางแสดงทุกโปรเซส: `PID`, ชื่อ, CPU%, RAM, Flags (เช่น leak / spike), และ Role (Foreground / Background)
  - ช่องค้นหาโปรเซสตามชื่อหรือ PID
  - ปรับ sort ได้ตาม `CPU / Memory / PID / Name`

- **Optimize Tab**
  - ปรับ **CPU Priority** (Idle → Realtime)
  - ปรับ **Memory Priority** (VeryLow–High)
  - สั่ง **Trim RAM** (ใช้ `EmptyWorkingSet`) เพื่อลด working set ของโปรเซส
  - ตั้งค่า **CPU Affinity**:
    - All cores  
    - Half cores (even / odd)  
    - First 2 cores
  - สั่ง **Suspend / Resume / Kill** โปรเซส
  - ปุ่ม **Revert Changes** เพื่อย้อนกลับ Priority / Memory priority / Affinity ที่ OptiCores เคยเปลี่ยนให้
  - แสดง **Effects Panel** วัดก่อน-หลัง (ΔCPU, ΔRAM) ทุกครั้งที่กด action

- **Game Mode & Background Governor**
  - **Game Mode**
    - สลับเป็น High Performance power plan
    - Boost foreground app (เพิ่ม CPU priority + memory priority)
  - **Background Governor**
    - ลด Priority / Memory priority ของ background apps
    - เปิด power throttling แบบ Eco สำหรับโปรเซสบางตัว
    - ใช้ Windows Job Object (ถ้ามี `win32job`)

- **Profiles**
  - `Gaming` เน้น High Performance, เปิด Game Mode + Governor
  - `Creator` เน้นงานตัดต่อ/render, Balanced plan + Governor
  - `Everyday` ใช้งานทั่วไป, Balanced plan, ไม่บีบ background เยอะ

- **Startup Manager**
  - อ่านค่า startup จาก:
    - Registry: `HKCU/HKLM\Software\Microsoft\Windows\CurrentVersion\Run`
    - User / Common Startup folder (`.lnk`)
  - Enable / Disable ได้แบบ reversible:
    - Registry: backup ไว้ที่ `Software\OptiCores\StartupBackup`
    - Shortcut: ย้ายไปโฟลเดอร์ `Disabled by OptiCores`

- **Insights (Live Graphs)**
  - กราฟ Live: CPU / RAM / GPU (%)
  - ใช้ `matplotlib` + `GPUtil` (ถ้ามี GPU ที่รองรับ)

- **Rules Automation (No typing, Jigsaw style)**
  - สร้าง rule แบบคลิกเลือก:
    - Pattern (เช่น `chrome.exe`, `updater`, `launcher`, ฯลฯ)
    - Scope: `Always / Foreground / Background`
    - Metric: CPU > X%
    - Action: `lower_priority`, `trim`, `eco_throttle`, `kill`
  - มี `DEFAULT_RULES` ตัวอย่าง เช่น:
    - ลด Priority ของ `chrome.exe` ถ้าใช้ CPU สูงใน background
    - throttle processes ที่ชื่อมีคำว่า `updater`

- **Advisor**
  - สแกนระบบแล้วเสนอคำแนะนำเป็นแถวๆ:
    - BG CPU สูงเกิน threshold
    - ใช้ RAM เยอะเกิน threshold
    - แนวโน้ม memory leak จาก HealthWatcher
  - กด Apply เฉพาะรายการที่เลือก หรือ Apply all safe ได้

- **Settings**
  - ตั้งค่า Threshold:
    - Background CPU high (%)
    - Heavy RAM (MB)
  - ตั้งค่า **Refresh interval** (1–10 วินาที)
  - ตั้งค่า **Custom whitelist** (ชื่อโปรเซสที่ไม่อยากให้แอปไปยุ่ง)

- **Reports & Logs**
  - Export snapshot ของตาราง process เป็น `.csv`
  - Export effects history เป็น `.json`
  - Activity log ในตัวแอป

---

## Tech Stack

- Python
- [customtkinter](https://github.com/TomSchimansky/CustomTkinter) สำหรับ UI สไตล์ modern
- `psutil` สำหรับอ่านข้อมูลโปรเซส/ระบบ
- `matplotlib` สำหรับกราฟ CPU/RAM/GPU
- `GPUtil` (ถ้ามี) สำหรับอ่าน GPU load
- `pywin32` (`win32api`, `win32gui`, `win32process`, `win32con`, `win32job`, `winreg`)
- `ctypes` + Windows API:
  - `SetProcessInformation` (memory priority, power throttling)
  - `EmptyWorkingSet` (trim working set)

---

## 🔧 Requirements

- Windows 10 / 11 (64-bit)
- Python 3.10+ (แนะนำให้ใช้ 64-bit)
- Packages (ผ่าน `pip`):

```bash
pip install psutil customtkinter GPUtil Pillow matplotlib pywin32
