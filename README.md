# OptiCores

**OptiCores** is the Ultimate CPU and Priority Optimizer built for Windows. It provides a suite of advanced tools to manage background tasks, free up RAM, optimize gaming performance, and keep your system running at peak efficiency through a beautifully designed, modern UI.

## Key Features

OptiCores is divided into specialized modules accessible from the sidebar. Here is an overview of what each tab can do for your system:

### 1. Dashboard
Your command center. View real-time system metrics (CPU, RAM, Disk, Network) in sleek, animated graphs. Access quick actions like "Optimize All" and "Game Mode" right from the top bar.

### 2. Processes
A detailed process manager. View every running application, its CPU/RAM usage, and priority. Right-click to change priorities, restrict CPU affinity, or terminate unresponsive tasks.

### 3. Active
Focuses only on your currently active foreground applications and their child processes, allowing you to monitor exactly what is taking up resources right now.

### 4. Activity
A real-time log of all system changes, optimization actions, and process terminations. Track exactly what OptiCores is doing behind the scenes.

### 5. Booster
The performance acceleration hub. Toggle core features like:
*   **OptiBalance:** Dynamically re-balances CPU priority.
*   **Game Mode:** Halts background services to give games 100% of your resources.
*   **Memory Optimizer:** Trims unused RAM from idle processes.
*   **Foreground Booster:** Gives maximum priority to your active window.

### 6. Tools
A collection of advanced system utilities including quick-access shortcuts to Windows native tools, power plan management, and service configurations.

### 7. Network
Monitor real-time download and upload speeds. See exactly which applications are consuming your bandwidth.

### 8. Storage
Analyze disk usage across all your drives. View total, used, and free space with visual progress bars.

### 9. Cleaner
A built-in junk cleaner. Scan for temporary files, cache, and system logs, and securely delete them to free up valuable storage space.

### 10. Benchmark
Test your system's performance. Run quick CPU multi-core and single-core stress tests to see how your computer handles heavy workloads.

### 11. SystemInfo
Detailed hardware specifications. View information about your CPU topology (P-Cores vs E-Cores), RAM, Motherboard, and Operating System version.

### 12. Power
Advanced power management. Instantly switch between Windows Power Plans (Power Saver, Balanced, High Performance, Ultimate Performance) to heavily optimize for battery or speed.

### 13. Overlay
Configure the OptiCores floating overlay. Pin a tiny, transparent system monitor to your screen so you can track FPS, CPU, and RAM while playing games.

### 14. Optimizer
Deep-level system optimizations. Apply physical-core-only affinities, toggle SysMain (Superfetch), and prioritize background I/O tasks.

### 15. Rules
Create automated conditions for your applications. Prevent specific programs from ever starting, or permanently force your favorite game to always launch with "High" priority.

### 16. Startup
Take control of your boot times. Enable, disable, or delay programs that normally start when Windows logs in.

### 17. Insights
Deep analytics and historical data. View how your system resource usage has trended over the past hours or days.

### 18. AIAssistant
Your built-in PC guru. Ask questions in natural language about how to optimize your PC, or get explanations on what specific OptiCores features do.

*(Note: There is also a **Settings** tab to customize the app theme, refresh rates, custom whitelists, and backup/restore your configuration).*

## Installation

1. Download the `OptiCores_Setup.exe` from the [Releases](https://github.com/BallBean/OptiCores/releases/tag/OptiCore) page.
2. Run the installer and follow the Setup Wizard.
3. Launch OptiCores! 

*Note: OptiCores requires Administrator privileges to modify system priorities and power plans.*

## Built With

*   **Python 3** - The core logic
*   **CustomTkinter** - The modern, dark-themed UI
*   **Psutil** - System telemetry and process management
*   **PyInstaller and Inno Setup** - App packaging

---
*Disclaimer: Modifying deep system settings and process priorities can cause system instability if misconfigured. Use Auto-Pilot for safe, recommended settings.*
