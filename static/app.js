(function () {
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");
    const fileList = document.getElementById("fileList");
    const goButton = document.getElementById("goButton");
    const clearBtn = document.getElementById("clearBtn");
    const actions = document.getElementById("actions");
    const resultsSummary = document.getElementById("resultsSummary");
    const sourceDirInput = document.getElementById("sourceDir");
    const outputDirInput = document.getElementById("outputDir");
    const outputRow = document.querySelector(".output-row");
    const toggles = document.querySelectorAll(".toggle");

    const ACCEPTED_TYPES = new Set([
        "image/jpeg", "image/png", "image/webp", "application/pdf",
    ]);
    const ACCEPTED_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp", ".pdf"]);

    const browseSource = document.getElementById("browseSource");
    const browseOutput = document.getElementById("browseOutput");

    let files = [];
    let mode = "rename";
    let processing = false;
    let dragCounter = 0;

    // --- Folder pickers ---
    async function pickFolder(prompt) {
        const resp = await fetch("/api/pick-folder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt }),
        });
        const data = await resp.json();
        return data.path;
    }

    browseSource.addEventListener("click", async () => {
        const path = await pickFolder("Select your receipt folder");
        if (path) sourceDirInput.value = path;
    });

    browseOutput.addEventListener("click", async () => {
        const path = await pickFolder("Select output folder");
        if (path) outputDirInput.value = path;
    });

    // --- Mode toggle ---
    toggles.forEach((btn) => {
        btn.addEventListener("click", () => {
            if (processing) return;
            toggles.forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            mode = btn.dataset.mode;
            outputRow.classList.toggle("hidden", mode !== "copy");
        });
    });

    // --- Drag and drop ---
    dropZone.addEventListener("dragenter", (e) => {
        e.preventDefault();
        dragCounter++;
        dropZone.classList.add("drag-over");
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
    });

    dropZone.addEventListener("dragleave", () => {
        dragCounter--;
        if (dragCounter === 0) {
            dropZone.classList.remove("drag-over");
        }
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dragCounter = 0;
        dropZone.classList.remove("drag-over");
        if (processing) return;
        addFiles(e.dataTransfer.files);
    });

    dropZone.addEventListener("click", () => {
        if (!processing) fileInput.click();
    });

    fileInput.addEventListener("change", () => {
        addFiles(fileInput.files);
        fileInput.value = "";
    });

    function isAccepted(file) {
        if (ACCEPTED_TYPES.has(file.type)) return true;
        const ext = "." + file.name.split(".").pop().toLowerCase();
        return ACCEPTED_EXTS.has(ext);
    }

    function addFiles(newFiles) {
        const accepted = Array.from(newFiles).filter(isAccepted);
        if (accepted.length === 0) return;

        // Avoid duplicates by name
        const existing = new Set(files.map((f) => f.name));
        accepted.forEach((f) => {
            if (!existing.has(f.name)) {
                files.push(f);
                existing.add(f.name);
            }
        });

        renderFileList();
        actions.hidden = false;
        resultsSummary.hidden = true;
    }

    // --- File list rendering ---
    function renderFileList() {
        fileList.hidden = files.length === 0;
        fileList.innerHTML = files
            .map(
                (f, i) => `
            <div class="file-item" data-index="${i}" id="file-${i}">
                <span class="file-icon">${f.name.toLowerCase().endsWith(".pdf") ? "&#128196;" : "&#128247;"}</span>
                <span class="file-name">${escapeHtml(f.name)}</span>
                <span class="file-status" id="status-${i}">Ready</span>
                <button class="file-remove" data-index="${i}">&times;</button>
            </div>`
            )
            .join("");

        // Remove buttons
        fileList.querySelectorAll(".file-remove").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                if (processing) return;
                const idx = parseInt(btn.dataset.index);
                files.splice(idx, 1);
                renderFileList();
                if (files.length === 0) {
                    actions.hidden = true;
                }
            });
        });
    }

    // --- Clear ---
    clearBtn.addEventListener("click", () => {
        if (processing) return;
        files = [];
        fileList.innerHTML = "";
        fileList.hidden = true;
        actions.hidden = true;
        resultsSummary.hidden = true;
    });

    // --- Go button ---
    goButton.addEventListener("click", async () => {
        const sourceDir = sourceDirInput.value.trim();
        if (!sourceDir) {
            sourceDirInput.focus();
            sourceDirInput.style.borderColor = "#e74c3c";
            setTimeout(() => (sourceDirInput.style.borderColor = ""), 1500);
            return;
        }
        if (mode === "copy" && !outputDirInput.value.trim()) {
            outputDirInput.focus();
            outputDirInput.style.borderColor = "#e74c3c";
            setTimeout(() => (outputDirInput.style.borderColor = ""), 1500);
            return;
        }
        if (files.length === 0 || processing) return;

        processing = true;
        goButton.disabled = true;
        goButton.textContent = "Processing...";
        goButton.classList.add("processing");
        resultsSummary.hidden = true;

        // Remove all X buttons during processing
        fileList.querySelectorAll(".file-remove").forEach((b) => (b.hidden = true));

        const results = await processFiles(sourceDir);
        showSummary(results);

        processing = false;
        goButton.disabled = false;
        goButton.textContent = "Go";
        goButton.classList.remove("processing");
    });

    // --- Process files with concurrency ---
    async function processFiles(sourceDir) {
        const results = [];
        const queue = files.map((f, i) => ({ file: f, index: i }));
        const CONCURRENCY = 3;

        async function worker() {
            while (queue.length > 0) {
                const { file, index } = queue.shift();
                updateStatus(index, "processing");

                try {
                    const formData = new FormData();
                    formData.append("file", file);
                    formData.append("source_dir", sourceDir);
                    formData.append("mode", mode);
                    if (mode === "copy") {
                        formData.append("output_dir", outputDirInput.value.trim());
                    }

                    const resp = await fetch("/api/process", {
                        method: "POST",
                        body: formData,
                    });
                    const result = await resp.json();

                    if (result.status === "success") {
                        updateStatus(index, "success", result.new_name);
                    } else {
                        updateStatus(index, "error", null, result.error);
                    }
                    results.push(result);
                } catch (err) {
                    updateStatus(index, "error", null, err.message);
                    results.push({ status: "error", error: err.message });
                }
            }
        }

        await Promise.all(
            Array.from({ length: Math.min(CONCURRENCY, files.length) }, () => worker())
        );
        return results;
    }

    function updateStatus(index, status, newName, error) {
        const item = document.getElementById(`file-${index}`);
        const statusEl = document.getElementById(`status-${index}`);
        if (!item || !statusEl) return;

        item.className = `file-item ${status}`;

        if (status === "processing") {
            statusEl.innerHTML = '<div class="spinner"></div>';
        } else if (status === "success") {
            statusEl.innerHTML = `<span class="new-name">${escapeHtml(newName)}</span>`;
        } else if (status === "error") {
            statusEl.innerHTML = `<span class="error-msg">${escapeHtml(error || "Failed")}</span>`;
        }
    }

    function showSummary(results) {
        const successes = results.filter((r) => r.status === "success").length;
        const errors = results.filter((r) => r.status === "error").length;

        resultsSummary.hidden = false;
        if (errors === 0) {
            resultsSummary.className = "results-summary all-success";
            resultsSummary.textContent = `All ${successes} receipt${successes !== 1 ? "s" : ""} renamed successfully.`;
        } else {
            resultsSummary.className = "results-summary has-errors";
            resultsSummary.textContent = `${successes} renamed, ${errors} failed.`;
        }
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }
})();
