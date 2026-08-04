from pathlib import Path

path = Path("server.py")
text = path.read_text()

old = "        self.shutting_down = threading.Event()\n        self._event_bus: list[dict[str, Any]] = []"
new = "        self.shutting_down = threading.Event()\n        self.worker_threads: set[threading.Thread] = set()\n        self._event_bus: list[dict[str, Any]] = []"
if old not in text and new not in text:
    raise SystemExit("JobManager worker set insertion point not found")
text = text.replace(old, new, 1)

old = '        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"job-{job.id}").start()'
new = '        self._start_worker(job, name=f"job-{job.id}")'
if old not in text and new not in text:
    raise SystemExit("JobManager create worker call not found")
text = text.replace(old, new, 1)

marker = "        self.store.upsert(record, output, output_base)\n\n    @staticmethod\n    def _read_output"
replacement = """        self.store.upsert(record, output, output_base)

    def _start_worker(self, job: Job, *, name: str) -> threading.Thread:
        thread = threading.Thread(target=self._run_tracked, args=(job,), daemon=True, name=name)
        with self.lock:
            self.worker_threads.add(thread)
        thread.start()
        return thread

    def _run_tracked(self, job: Job) -> None:
        try:
            self._run(job)
        finally:
            with self.lock:
                self.worker_threads.discard(threading.current_thread())

    @staticmethod
    def _read_output"""
if marker not in text and "def _start_worker(self, job: Job" not in text:
    raise SystemExit("JobManager worker helper insertion point not found")
text = text.replace(marker, replacement, 1)

old = """    def shutdown(self) -> None:
        self.shutting_down.set()
        with self.lock:
            active = [job.id for job in self.jobs.values() if job.status not in TERMINAL_STATES]
        for job_id in active:
            self.stop(job_id)
"""
new = """    def shutdown(self) -> None:
        self.shutting_down.set()
        with self.lock:
            active = [job.id for job in self.jobs.values() if job.status not in TERMINAL_STATES]
        for job_id in active:
            self.stop(job_id)

        deadline = time.monotonic() + 15.0
        current = threading.current_thread()
        while time.monotonic() < deadline:
            with self.lock:
                workers = [thread for thread in self.worker_threads if thread is not current and thread.is_alive()]
            if not workers:
                break
            for thread in workers:
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    break
                thread.join(timeout=min(0.25, remaining))

        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            self._persist(job, force=True)
"""
if old not in text and new not in text:
    raise SystemExit("JobManager shutdown block not found")
text = text.replace(old, new, 1)

old = '        threading.Thread(target=self.manager._run, args=(job,), daemon=True, name=f"job-retry-{job.id}").start()'
new = '        self.manager._start_worker(job, name=f"job-retry-{job.id}")'
if old not in text and new not in text:
    raise SystemExit("Retry worker call not found")
text = text.replace(old, new, 1)

path.write_text(text)
