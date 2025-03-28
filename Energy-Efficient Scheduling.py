import time
from collections import deque
import random
import threading
import queue
import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# Simulated CPU frequency levels (in GHz) and power consumption (relative units)
FREQUENCY_LEVELS = {
    "low": {"freq": 0.8, "power": 0.5, "color": "#A2D9A2"},  # Soft green
    "mid": {"freq": 1.2, "power": 1.0, "color": "#FFFFB3"},  # Pale yellow
    "high": {"freq": 2.0, "power": 2.0, "color": "#FF9999"}  # Soft red
}

class Task:
    def __init__(self, task_id, priority, est_exec_time, deadline=None, arrival_time=None):
        self.task_id = task_id
        self.priority = priority
        self.est_exec_time = est_exec_time
        self.deadline = deadline if deadline else float('inf')
        self.arrival_time = arrival_time if arrival_time else time.time() * 1000
        self.actual_exec_time = None
        self.start_time = None
        self.finish_time = None
        self.efficient_energy = self.calculate_efficient_energy()

    def calculate_efficient_energy(self):
        if self.priority == 1:
            freq = FREQUENCY_LEVELS["high"]["freq"]
            power = FREQUENCY_LEVELS["high"]["power"]
        else:
            slack = self.deadline - (self.arrival_time + self.est_exec_time)
            if slack > 200:
                freq = FREQUENCY_LEVELS["low"]["freq"]
                power = FREQUENCY_LEVELS["low"]["power"]
            elif slack > 50:
                freq = FREQUENCY_LEVELS["mid"]["freq"]
                power = FREQUENCY_LEVELS["mid"]["power"]
            else:
                freq = FREQUENCY_LEVELS["high"]["freq"]
                power = FREQUENCY_LEVELS["high"]["power"]
        exec_time = self.est_exec_time * (2.0 / freq)
        return power * (exec_time / 1000)

class Core:
    def __init__(self, core_id, gui):
        self.core_id = core_id
        self.task_queue = deque()
        self.load_history = []
        self.current_freq = "low"
        self.energy_consumed = 0
        self.running = False
        self.lock = threading.Lock()
        self.gui = gui
        self.deadline_misses = 0
        self.current_task = None
        self.completed_tasks = []

    def moving_average(self, window=10):
        with self.lock:
            if not self.load_history:
                return 0
            recent = self.load_history[-window:] if len(self.load_history) > window else self.load_history
            return sum(recent) / len(recent)

    def set_cpu_frequency(self, task, current_time):
        load = self.moving_average() / 100
        slack = task.deadline - (current_time + task.est_exec_time)
        with self.lock:
            if task.priority == 1:
                self.current_freq = "high"
            else:
                if slack > 200:
                    self.current_freq = "low" if load < 40 else "mid"
                else:
                    self.current_freq = "high" if slack < 50 else "mid"

    def execute_task(self, task, current_time):
        with self.lock:
            self.current_task = task
            self.gui.update_running_processes()
            freq = FREQUENCY_LEVELS[self.current_freq]["freq"]
            base_time = task.est_exec_time * (2.0 / freq)
            task.actual_exec_time = base_time + random.uniform(-2, 2)
            task.start_time = current_time
        
        start_real_time = time.time()
        exec_duration = task.actual_exec_time / 1000
        while time.time() - start_real_time < exec_duration:
            time.sleep(0.01)
            self.gui.update_running_processes()
        
        with self.lock:
            task.finish_time = time.time() * 1000
            power = FREQUENCY_LEVELS[self.current_freq]["power"]
            energy = power * (task.actual_exec_time / 1000)
            self.energy_consumed += energy
            self.load_history.append(task.actual_exec_time)
            if task.finish_time > task.deadline:
                self.deadline_misses += 1
            self.completed_tasks.append({
                'task_id': task.task_id,
                'priority': task.priority,
                'freq': self.current_freq,
                'finish_time': task.finish_time,
                'actual_exec_time': task.actual_exec_time
            })
            self.current_task = None
        
        latency = task.finish_time - task.arrival_time
        log_msg = (f"Core {self.core_id} | Task {task.task_id}: Freq={self.current_freq}, "
                   f"ExecTime={task.actual_exec_time:.2f}ms, Energy={energy:.2f}J, "
                   f"Latency={latency:.2f}ms, DeadlineMet={task.finish_time <= task.deadline}")
        self.gui.update_log(log_msg)
        self.gui.queue_gantt_update(self.core_id, task.task_id, task.priority, task.start_time, task.finish_time, self.current_freq)
        self.gui.update_running_processes()

    def run(self):
        while self.running and (self.task_queue or not self.gui.task_pool.empty()):
            if not self.task_queue:
                time.sleep(0.1)
                continue
            task = self.task_queue.popleft()
            current_time = time.time() * 1000
            self.set_cpu_frequency(task, current_time)
            self.execute_task(task, current_time)
            self.gui.update_metrics()

class EOTS:
    def __init__(self, root):
        self.root = root
        self.root.title("Energy-Optimized Task Scheduler")
        self.root.geometry("800x600")  # Smaller main window since Gantt is separate
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TLabel", font=("Helvetica", 10))
        self.style.configure("TButton", font=("Helvetica", 10), padding=5)
        self.style.configure("TFrame", background="#f0f0f0")
        
        self.cores = []
        self.task_pool = queue.Queue()
        self.total_energy = 0
        self.total_efficient_energy = 0
        self.tasks_completed = 0
        self.deadline_misses = 0
        self.start_time = None
        self.running = False
        self.gantt_data = {}
        self.gui_lock = threading.Lock()
        self.gantt_update_queue = queue.Queue()
        self.scheduling_algorithms = ["Priority Scheduling", "EDF (Earliest Deadline First)", "Round Robin", "Hybrid Energy-Aware Priority Scheduling"]
        self.selected_algorithm = tk.StringVar(value=self.scheduling_algorithms[3])
        self.gantt_window = None  # For the separate Gantt chart window
        self.setup_gui()

    def setup_gui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill="both", expand=True)

        # Configuration Section
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        config_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(config_frame, text="Number of Cores:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.num_cores_var = tk.IntVar(value=4)
        ttk.Entry(config_frame, textvariable=self.num_cores_var, width=10).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(config_frame, text="Number of Tasks:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.num_tasks_var = tk.IntVar(value=100)
        ttk.Entry(config_frame, textvariable=self.num_tasks_var, width=10).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(config_frame, text="Scheduling Algorithm:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.scheduling_dropdown = ttk.Combobox(config_frame, textvariable=self.selected_algorithm, 
                                               values=self.scheduling_algorithms, state="readonly", width=30)
        self.scheduling_dropdown.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        button_frame = ttk.Frame(config_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text="Start", command=self.start_simulation).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Stop", command=self.stop_simulation).pack(side="left", padx=5)

        # Metrics Section
        metrics_frame = ttk.LabelFrame(main_frame, text="Metrics", padding="10")
        metrics_frame.pack(fill="x", pady=(0, 10))

        self.energy_label = ttk.Label(metrics_frame, text="Total Energy: 0.00 J")
        self.energy_label.pack(anchor="w")
        self.efficient_energy_label = ttk.Label(metrics_frame, text="Efficient Energy: 0.00 J")
        self.efficient_energy_label.pack(anchor="w")
        self.efficiency_label = ttk.Label(metrics_frame, text="Energy Efficiency: 0%")
        self.efficiency_label.pack(anchor="w")
        self.tasks_label = ttk.Label(metrics_frame, text="Tasks Completed: 0")
        self.tasks_label.pack(anchor="w")
        self.misses_label = ttk.Label(metrics_frame, text="Deadline Misses: 0")
        self.misses_label.pack(anchor="w")
        self.progress = ttk.Progressbar(metrics_frame, maximum=100, mode="determinate", length=300)
        self.progress.pack(fill="x", pady=5)

        # Process Information Section
        process_frame = ttk.LabelFrame(main_frame, text="Running and Past Process Information", padding="10")
        process_frame.pack(fill="both", expand=True, pady=(0, 10))  # Expanded to use more space

        self.process_canvas = tk.Canvas(process_frame, height=200)  # Increased height
        self.process_text = tk.Text(self.process_canvas, font=("Courier", 9), wrap='none', bg="#ffffff", relief="flat")
        v_scrollbar = ttk.Scrollbar(process_frame, orient="vertical", command=self.process_text.yview)
        h_scrollbar = ttk.Scrollbar(process_frame, orient="horizontal", command=self.process_text.xview)
        self.process_text.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        self.process_canvas.pack(side=tk.LEFT, fill="both", expand=True)
        v_scrollbar.pack(side=tk.RIGHT, fill="y")
        h_scrollbar.pack(side=tk.BOTTOM, fill="x")
        self.process_canvas.create_window((0, 0), window=self.process_text, anchor="nw")
        self.process_text.bind("<Configure>", lambda e: self.process_canvas.configure(scrollregion=self.process_canvas.bbox("all")))

        # Execution Log Section
        log_frame = ttk.LabelFrame(main_frame, text="Execution Log", padding="10")
        log_frame.pack(fill="both", expand=True, pady=(0, 10))  # Expanded to use more space

        self.log_text = tk.Text(log_frame, height=8, font=("Courier", 9), bg="#ffffff", relief="flat")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill="y")

        # Status Bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief="sunken", anchor="w", padding=5)
        status_bar.pack(fill="x")

        # Gantt Chart Window (initialized but hidden)
        self.gantt_window = tk.Toplevel(self.root)
        self.gantt_window.title("Gantt Chart")
        self.gantt_window.geometry("1000x600")
        self.gantt_window.withdraw()  # Hide initially
        self.fig = Figure(figsize=(10, 5), dpi=100, facecolor="#f5f5f5")
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("#f9f9f9")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.gantt_window)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

        self.legend_patches = [
            plt.Rectangle((0, 0), 1, 1, facecolor=FREQUENCY_LEVELS["low"]["color"], edgecolor="black", label="Low Freq (P0)"),
            plt.Rectangle((0, 0), 1, 1, facecolor=FREQUENCY_LEVELS["mid"]["color"], edgecolor="black", label="Mid Freq (P0)"),
            plt.Rectangle((0, 0), 1, 1, facecolor=FREQUENCY_LEVELS["high"]["color"], edgecolor="black", label="High Freq (P1/P0)")
        ]

        self.gantt_thread = threading.Thread(target=self.process_gantt_updates, daemon=True)
        self.gantt_thread.start()

    def generate_tasks(self):
        num_tasks = self.num_tasks_var.get()
        self.total_efficient_energy = 0
        for i in range(num_tasks):
            priority = random.choice([0, 1])
            est_exec_time = random.randint(10, 20)
            deadline = (time.time() * 1000) + random.randint(50, 150) if priority == 0 else None
            task = Task(i, priority, est_exec_time, deadline)
            self.task_pool.put(task)
            self.total_efficient_energy += task.efficient_energy

    def assign_tasks(self):
        with self.gui_lock:
            tasks = []
            while not self.task_pool.empty():
                tasks.append(self.task_pool.get())
            
            algorithm = self.selected_algorithm.get()
            if algorithm == "Priority Scheduling":
                tasks.sort(key=lambda t: t.priority, reverse=True)
                for task in tasks:
                    core = min(self.cores, key=lambda c: len(c.task_queue))
                    core.task_queue.append(task)
            elif algorithm == "EDF (Earliest Deadline First)":
                tasks.sort(key=lambda t: t.deadline)
                for task in tasks:
                    core = min(self.cores, key=lambda c: len(c.task_queue))
                    core.task_queue.append(task)
            elif algorithm == "Round Robin":
                for i, task in enumerate(tasks):
                    core = self.cores[i % len(self.cores)]
                    core.task_queue.append(task)
            else:  # Hybrid Energy-Aware Priority Scheduling
                for task in tasks:
                    core = min(self.cores, key=lambda c: len(c.task_queue))
                    core.task_queue.append(task)

    def start_simulation(self):
        if self.running:
            return
        self.running = True
        self.start_time = time.time() * 1000
        self.total_energy = 0
        self.total_efficient_energy = 0
        self.tasks_completed = 0
        self.deadline_misses = 0
        self.progress["value"] = 0
        self.gantt_data = {i: [] for i in range(self.num_cores_var.get())}
        self.ax.clear()
        self.canvas.draw()
        self.status_var.set("Simulation Running")
        self.gantt_window.deiconify()  # Show Gantt window

        num_cores = self.num_cores_var.get()
        self.cores = [Core(i, self) for i in range(num_cores)]
        self.generate_tasks()
        self.assign_tasks()

        for core in self.cores:
            core.running = True
            threading.Thread(target=core.run, daemon=True).start()

    def stop_simulation(self):
        self.running = False
        for core in self.cores:
            core.running = False
        self.update_metrics()
        self.update_running_processes()
        self.status_var.set("Simulation Stopped")
        if self.gantt_window:
            self.gantt_window.withdraw()  # Hide Gantt window

    def update_log(self, message):
        with self.gui_lock:
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.root.update_idletasks()

    def update_metrics(self):
        with self.gui_lock:
            self.total_energy = sum(core.energy_consumed for core in self.cores)
            self.tasks_completed = sum(len(core.load_history) for core in self.cores)
            self.deadline_misses = sum(core.deadline_misses for core in self.cores)

            self.energy_label.config(text=f"Total Energy: {self.total_energy:.2f} J")
            self.efficient_energy_label.config(text=f"Efficient Energy: {self.total_efficient_energy:.2f} J")
            efficiency = (self.total_efficient_energy / self.total_energy * 100) if self.total_energy > 0 else 0
            self.efficiency_label.config(text=f"Energy Efficiency: {efficiency:.1f}%")
            self.tasks_label.config(text=f"Tasks Completed: {self.tasks_completed}")
            self.misses_label.config(text=f"Deadline Misses: {self.deadline_misses}")
            self.progress["value"] = self.tasks_completed
            self.progress["maximum"] = self.num_tasks_var.get()
            self.root.update_idletasks()

    def update_running_processes(self):
        with self.gui_lock:
            self.process_text.config(state='normal')
            self.process_text.delete(1.0, tk.END)
            
            algorithm = self.selected_algorithm.get()
            running_header = f"RUNNING PROCESSES (Scheduling: {algorithm})\n"
            self.process_text.insert(tk.END, running_header)
            header = f"{'Core':<6} {'Task ID':<8} {'Priority':<9} {'Frequency':<10} {'Remaining Time (ms)':<20}\n"
            self.process_text.insert(tk.END, header)
            
            for core in self.cores:
                if core.current_task:
                    task = core.current_task
                    elapsed = (time.time() * 1000 - task.start_time) if task.start_time else 0
                    remaining = max(0, task.actual_exec_time - elapsed) if task.actual_exec_time else task.est_exec_time
                    line = (f"C{core.core_id:<5} T{task.task_id:<7} P{task.priority:<8} "
                            f"{core.current_freq:<9} {remaining:<19.1f}\n")
                    self.process_text.insert(tk.END, line)
                else:
                    line = f"C{core.core_id:<5} {'Idle':<7} {'-':<8} {'-':<9} {'-':<19}\n"
                    self.process_text.insert(tk.END, line)
            
            self.process_text.insert(tk.END, "\n" + "-"*60 + "\n\n")
            
            past_header = f"PAST PROCESSES (Scheduling: {algorithm})\n"
            self.process_text.insert(tk.END, past_header)
            past_header = f"{'Core':<6} {'Task ID':<8} {'Priority':<9} {'Frequency':<10} {'Exec Time (ms)':<15} {'Finish Time (ms)':<20}\n"
            self.process_text.insert(tk.END, past_header)
            
            for core in self.cores:
                for task in core.completed_tasks:
                    finish_time_relative = task['finish_time'] - self.start_time if self.start_time else 0
                    line = (f"C{core.core_id:<5} T{task['task_id']:<7} P{task['priority']:<8} "
                            f"{task['freq']:<9} {task['actual_exec_time']:<14.1f} {finish_time_relative:<19.1f}\n")
                    self.process_text.insert(tk.END, line)
            
            self.process_text.config(state='disabled')
            self.process_canvas.configure(scrollregion=self.process_canvas.bbox("all"))
            self.root.update_idletasks()

    def queue_gantt_update(self, core_id, task_id, priority, start_time, finish_time, freq):
        self.gantt_update_queue.put((core_id, task_id, priority, start_time, finish_time, freq))

    def process_gantt_updates(self):
        while True:
            try:
                updates = []
                while not self.gantt_update_queue.empty():
                    updates.append(self.gantt_update_queue.get())
                
                if updates and self.gantt_window.winfo_exists():  # Check if window still exists
                    with self.gui_lock:
                        max_time = 0
                        for core_id, task_id, priority, start_time, finish_time, freq in updates:
                            label = f"T{task_id}"
                            start = max(0, start_time - self.start_time)
                            finish = finish_time - self.start_time
                            self.gantt_data[core_id].append((label, start, finish, freq))
                            max_time = max(max_time, finish)

                        self.ax.clear()
                        time_window = max(1000, max_time * 1.1)
                        self.ax.set_xlim(0, time_window)
                        self.ax.set_ylim(-0.5, len(self.cores) - 0.5)
                        self.ax.set_facecolor("#f9f9f9")

                        for cid in range(len(self.cores)):
                            for task_label, start, finish, freq in self.gantt_data[cid]:
                                if finish > start:
                                    duration = finish - start
                                    color = FREQUENCY_LEVELS[freq]["color"]
                                    bar_height = 0.6
                                    self.ax.broken_barh(
                                        [(start, duration)],
                                        (cid - bar_height/2, bar_height),
                                        facecolors=color,
                                        edgecolor="black",
                                        linewidth=1.5,
                                        alpha=0.85
                                    )
                                    if duration > 30:
                                        text_x = start + duration / 2
                                        self.ax.text(text_x, cid, task_label, 
                                                   ha='center', va='center', fontsize=8, fontweight='bold', color="black")

                        self.ax.set_title("Task Execution Timeline", fontsize=14, fontweight='bold', pad=15)
                        self.ax.set_xlabel("Time (ms)", fontsize=12)
                        self.ax.set_ylabel("Cores", fontsize=12)
                        self.ax.set_yticks(range(len(self.cores)))
                        self.ax.set_yticklabels([f"C{cid}" for cid in range(len(self.cores))], fontsize=10)
                        self.ax.grid(True, linestyle='--', alpha=0.4, color="#cccccc")
                        self.ax.legend(handles=self.legend_patches, loc="upper center", 
                                     fontsize=10, bbox_to_anchor=(0.5, 1.1), ncol=3, 
                                     frameon=True, edgecolor="black", facecolor="#ffffff")
                        self.fig.tight_layout(pad=2.0)
                        self.canvas.draw()
                
                time.sleep(0.1)
            except Exception as e:
                print(f"Gantt update error: {e}")

def main():
    root = tk.Tk()
    app = EOTS(root)
    root.mainloop()

if __name__ == "__main__":
    main()