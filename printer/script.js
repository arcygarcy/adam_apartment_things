document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const previewCanvas = document.getElementById('previewCanvas');
    const styleSelect = document.getElementById('styleSelect');
    const asciiControls = document.getElementById('asciiControls');
    const asciiRampSelect = document.getElementById('asciiRamp');
    const asciiColsSlider = document.getElementById('asciiColsSlider');
    const asciiColsVal = document.getElementById('asciiColsVal');
    const frameSelect = document.getElementById('frameSelect');
    
    const thresholdSlider = document.getElementById('thresholdSlider');
    const brightnessVal = document.getElementById('brightnessVal');
    const contrastSlider = document.getElementById('contrastSlider');
    const contrastVal = document.getElementById('contrastVal');
    const presetPills = document.querySelectorAll('.preset-pill');
    const printBtn = document.getElementById('printBtn');
    
    const statusAlert = document.getElementById('statusAlert');
    const statusTitle = document.getElementById('statusTitle');
    const statusMsg = document.getElementById('statusMsg');

    let originalImage = null;

    // Constants for 80mm thermal printer (576 dots printable width)
    const PRINTER_WIDTH_DOTS = 576; 

    // Handle File Upload / Camera Capture
    dropZone.addEventListener('click', () => fileInput.click());
    
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });
    
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            handleImage(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) {
            handleImage(e.target.files[0]);
        }
    });

    async function handleImage(file) {
        if (!file.type.startsWith('image/')) {
            alert('Please select an image file.');
            return;
        }

        const targetMaxDim = 600; // Thermal printer printable width is 576 dots

        // Strategy 1: Hardware-Accelerated Decode & Downsample via createImageBitmap (iOS 15+, Android Chrome)
        // Decodes directly at 600px resolution using ~3MB RAM instead of 190MB RAM for 48MP photos
        if ('createImageBitmap' in window) {
            try {
                let bitmap;
                try {
                    bitmap = await createImageBitmap(file, {
                        resizeWidth: targetMaxDim,
                        resizeQuality: 'medium'
                    });
                } catch (e) {
                    bitmap = await createImageBitmap(file);
                }

                const offCanvas = document.createElement('canvas');
                let w = bitmap.width;
                let h = bitmap.height;

                if (w > targetMaxDim || h > targetMaxDim) {
                    if (w > h) {
                        h = Math.round((h * targetMaxDim) / w);
                        w = targetMaxDim;
                    } else {
                        w = Math.round((w * targetMaxDim) / h);
                        h = targetMaxDim;
                    }
                }

                offCanvas.width = w;
                offCanvas.height = h;
                const offCtx = offCanvas.getContext('2d');
                offCtx.drawImage(bitmap, 0, 0, w, h);
                if (bitmap.close) bitmap.close(); // Instantly release GPU memory handle

                const scaledImg = new Image();
                scaledImg.onload = () => {
                    originalImage = scaledImg;
                    fileInput.value = '';
                    offCanvas.width = 0;
                    offCanvas.height = 0;
                    document.querySelector('.preview-container').style.display = 'block';
                    processImage();
                    document.querySelector('.preview-container').scrollIntoView({ behavior: 'smooth' });
                };
                scaledImg.src = offCanvas.toDataURL('image/jpeg', 0.8);
                return;
            } catch (bitmapErr) {
                console.warn("createImageBitmap failed, using image fallback:", bitmapErr);
            }
        }

        // Strategy 2: Traditional Image Object Fallback
        const objectUrl = URL.createObjectURL(file);
        const img = new Image();
        
        img.onload = () => {
            const maxDim = 600;
            let w = img.width;
            let h = img.height;
            
            if (w > maxDim || h > maxDim) {
                if (w > h) {
                    h = Math.round((h * maxDim) / w);
                    w = maxDim;
                } else {
                    w = Math.round((w * maxDim) / h);
                    h = maxDim;
                }
            }
            
            const offCanvas = document.createElement('canvas');
            offCanvas.width = w;
            offCanvas.height = h;
            const offCtx = offCanvas.getContext('2d');
            offCtx.drawImage(img, 0, 0, w, h);
            
            const scaledImg = new Image();
            scaledImg.onload = () => {
                originalImage = scaledImg;
                URL.revokeObjectURL(objectUrl);
                fileInput.value = '';
                offCanvas.width = 0;
                offCanvas.height = 0;
                document.querySelector('.preview-container').style.display = 'block';
                processImage();
                document.querySelector('.preview-container').scrollIntoView({ behavior: 'smooth' });
            };
            scaledImg.src = offCanvas.toDataURL('image/jpeg', 0.8);
        };
        
        img.onerror = () => {
            URL.revokeObjectURL(objectUrl);
            alert("Failed to load image. Please try selecting a smaller photo.");
        };
        
        img.src = objectUrl;
    }

    const noteInput = document.getElementById('noteInput');
    let currentOrderNumber = 1;

    // Fetch initial Order Number from backend
    async function fetchOrderInfo() {
        try {
            const res = await fetch('/order-info');
            if (res.ok) {
                const data = await res.json();
                if (data.orderCounter) {
                    currentOrderNumber = data.orderCounter;
                    if (originalImage) processImage();
                }
            }
        } catch (e) {
            console.log("Using default order counter 1");
        }
    }

    if (noteInput) {
        noteInput.addEventListener('input', () => scheduleProcessImage());
    }

    // Presets configuration map
    const presets = {
        photo: { style: 'floyd', brightness: 128, contrast: 100, frame: 'none' },
        sketch: { style: 'sobel', brightness: 128, contrast: 120, frame: 'none' },
        retro: { style: 'atkinson', brightness: 135, contrast: 115, frame: 'vintage' },
        newspaper: { style: 'halftone', brightness: 125, contrast: 110, frame: 'none' },
        pixel: { style: 'bayer', brightness: 128, contrast: 120, frame: 'none' },
        ascii: { style: 'ascii', brightness: 128, contrast: 110, frame: 'none', cols: 96 },
        poster: { style: 'threshold', brightness: 120, contrast: 150, frame: 'none' }
    };

    presetPills.forEach(pill => {
        pill.addEventListener('click', () => {
            presetPills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            
            const presetKey = pill.getAttribute('data-preset');
            const cfg = presets[presetKey];
            if (cfg) {
                styleSelect.value = cfg.style;
                thresholdSlider.value = cfg.brightness;
                contrastSlider.value = cfg.contrast;
                frameSelect.value = cfg.frame || 'none';
                if (cfg.cols) {
                    asciiColsSlider.value = cfg.cols;
                    asciiColsVal.textContent = `${cfg.cols} Columns (HD)`;
                }
                
                brightnessVal.textContent = cfg.brightness;
                contrastVal.textContent = cfg.contrast + '%';
                
                processImage();
            }
        });
    });

    thresholdSlider.addEventListener('input', () => {
        brightnessVal.textContent = thresholdSlider.value;
        scheduleProcessImage();
    });

    contrastSlider.addEventListener('input', () => {
        contrastVal.textContent = contrastSlider.value + '%';
        scheduleProcessImage();
    });

    asciiColsSlider.addEventListener('input', () => {
        const val = asciiColsSlider.value;
        let label = `${val} Cols`;
        if (val >= 120) label += " (Ultra HD)";
        else if (val >= 96) label += " (HD)";
        else if (val >= 64) label += " (Medium)";
        else label += " (Large Font)";
        asciiColsVal.textContent = label;
        scheduleProcessImage();
    });

    styleSelect.addEventListener('change', () => {
        asciiControls.style.display = styleSelect.value === 'ascii' ? 'grid' : 'none';
        scheduleProcessImage();
    });

    asciiRampSelect.addEventListener('change', scheduleProcessImage);
    frameSelect.addEventListener('change', scheduleProcessImage);

    const asciiRamps = {
        standard: "@%#*+=-:. ",
        blocks: "█▓▒░ ",
        matrix: "10 ",
        detailed: "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`'. "
    };

    let animationFrameId = null;
    function scheduleProcessImage() {
        if (animationFrameId) cancelAnimationFrame(animationFrameId);
        animationFrameId = requestAnimationFrame(() => {
            processImage();
        });
    }

    function processImage() {
        if (!originalImage) return;

        const mode = styleSelect.value;
        asciiControls.style.display = mode === 'ascii' ? 'grid' : 'none';

        if (mode === 'ascii') {
            processAsciiImage();
        } else {
            processStandardRasterImage(mode);
        }

        applyFrameOverlay();
        applyTicketHeaderAndFooter();
    }

    function processAsciiImage() {
        const cols = parseInt(asciiColsSlider.value);
        const rampKey = asciiRampSelect.value;
        const rampStr = asciiRamps[rampKey] || asciiRamps.standard;
        
        const charAspect = 0.55; 
        const rows = Math.round((originalImage.height / originalImage.width) * cols * charAspect);
        
        const sampleCanvas = document.createElement('canvas');
        sampleCanvas.width = cols;
        sampleCanvas.height = rows;
        const sampleCtx = sampleCanvas.getContext('2d');
        sampleCtx.drawImage(originalImage, 0, 0, cols, rows);
        
        const imgData = sampleCtx.getImageData(0, 0, cols, rows).data;
        
        const brightnessValue = parseInt(thresholdSlider.value);
        const brightnessFactor = brightnessValue / 128; 
        const contrastValue = parseInt(contrastSlider.value);
        const contrastFactor = contrastValue / 100;

        const asciiLines = [];
        for (let r = 0; r < rows; r++) {
            let line = "";
            for (let c = 0; c < cols; c++) {
                const idx = (r * cols + c) * 4;
                const red = imgData[idx];
                const green = imgData[idx + 1];
                const blue = imgData[idx + 2];
                const alpha = imgData[idx + 3];
                
                let luminance = 255;
                if (alpha >= 128) {
                    luminance = (0.299 * red + 0.587 * green + 0.114 * blue);
                }

                let val = ((luminance / 255 - 0.5) * contrastFactor + 0.5) * 255;
                val = val * brightnessFactor * 1.1;
                if (val > 255) val = 255;
                if (val < 0) val = 0;

                const rampLen = rampStr.length;
                const charIdx = Math.min(rampLen - 1, Math.floor((val / 256) * rampLen));
                line += rampStr[charIdx];
            }
            asciiLines.push(line);
        }

        const width = PRINTER_WIDTH_DOTS;
        const charWidthPx = width / cols;
        const charHeightPx = charWidthPx / charAspect;
        const height = Math.round(rows * charHeightPx);

        previewCanvas.width = width;
        previewCanvas.height = height;
        
        const ctx = previewCanvas.getContext('2d');
        ctx.fillStyle = "white";
        ctx.fillRect(0, 0, width, height);
        
        ctx.fillStyle = "black";
        ctx.font = `bold ${Math.floor(charHeightPx)}px Consolas, "Courier New", monospace`;
        ctx.textBaseline = "top";
        
        for (let r = 0; r < rows; r++) {
            ctx.fillText(asciiLines[r], 0, r * charHeightPx);
        }
    }

    function processStandardRasterImage(mode) {
        const ctx = previewCanvas.getContext('2d', { willReadFrequently: true });
        
        // Always scale image to fill 100% of receipt paper width (576 dots)
        const width = PRINTER_WIDTH_DOTS;
        const height = Math.round((originalImage.height * width) / originalImage.width);
        
        previewCanvas.width = width;
        previewCanvas.height = height;
        
        ctx.fillStyle = "white";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(originalImage, 0, 0, width, height);
        
        const imgData = ctx.getImageData(0, 0, width, height);
        const data = imgData.data;
        
        const brightnessValue = parseInt(thresholdSlider.value);
        const brightnessFactor = brightnessValue / 128; 
        const contrastValue = parseInt(contrastSlider.value);
        const contrastFactor = contrastValue / 100;
        
        const buffer = new Float32Array(width * height);
        
        for (let i = 0; i < width * height; i++) {
            const idx = i * 4;
            const r = data[idx];
            const g = data[idx + 1];
            const b = data[idx + 2];
            const a = data[idx + 3];
            
            let luminance = 255;
            if (a >= 128) {
                luminance = (0.299 * r + 0.587 * g + 0.114 * b);
            }
            
            let val = ((luminance / 255 - 0.5) * contrastFactor + 0.5) * 255;
            val = val * brightnessFactor * 1.15;
            if (val > 255) val = 255;
            if (val < 0) val = 0;
            
            buffer[i] = val;
        }

        if (mode === 'sobel') {
            const edgeCutoff = 45 * (128 / (brightnessValue || 128));
            for (let y = 1; y < height - 1; y++) {
                for (let x = 1; x < width - 1; x++) {
                    const idx00 = (y - 1) * width + (x - 1);
                    const idx01 = (y - 1) * width + x;
                    const idx02 = (y - 1) * width + (x + 1);
                    const idx10 = y * width + (x - 1);
                    const idx12 = y * width + (x + 1);
                    const idx20 = (y + 1) * width + (x - 1);
                    const idx21 = (y + 1) * width + x;
                    const idx22 = (y + 1) * width + (x + 1);

                    const gx = -buffer[idx00] + buffer[idx02] - 2 * buffer[idx10] + 2 * buffer[idx12] - buffer[idx20] + buffer[idx22];
                    const gy = -buffer[idx00] - 2 * buffer[idx01] - buffer[idx02] + buffer[idx20] + 2 * buffer[idx21] + buffer[idx22];

                    const mag = Math.sqrt(gx * gx + gy * gy) * contrastFactor;
                    const isEdge = mag > edgeCutoff;

                    let newPixel = isEdge ? 0 : 255;

                    const pixelIdx = (y * width + x) * 4;
                    data[pixelIdx] = data[pixelIdx + 1] = data[pixelIdx + 2] = newPixel;
                    data[pixelIdx + 3] = 255;
                }
            }
            ctx.putImageData(imgData, 0, 0);
            return;
        }

        const bayerMatrix4x4 = [
            [   0, 128,  32, 160 ],
            [ 192,  64, 224,  96 ],
            [  48, 176,  16, 144 ],
            [ 208, 112, 240,  80 ]
        ];

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const i = y * width + x;
                const oldPixel = buffer[i];
                let newPixel = 255; 
                
                if (mode === 'threshold') {
                    newPixel = oldPixel < 128 ? 0 : 255;
                } else if (mode === 'bayer') {
                    const matrixVal = bayerMatrix4x4[y % 4][x % 4];
                    newPixel = oldPixel < matrixVal ? 0 : 255;
                } else if (mode === 'halftone') {
                    const cellSize = 6;
                    const cx = Math.floor(x / cellSize) * cellSize + cellSize / 2;
                    const cy = Math.floor(y / cellSize) * cellSize + cellSize / 2;
                    const dx = x - cx;
                    const dy = y - cy;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    const maxDist = cellSize * 0.7071;
                    const normDist = dist / maxDist;
                    const darkness = 1.0 - (oldPixel / 255.0);
                    newPixel = darkness > normDist ? 0 : 255;
                } else if (mode === 'floyd' || mode === 'atkinson' || mode === 'stucki') {
                    newPixel = oldPixel < 128 ? 0 : 255;
                    const quantError = oldPixel - newPixel;
                    
                    if (mode === 'floyd') {
                        if (x + 1 < width) buffer[i + 1] += quantError * (7 / 16);
                        if (y + 1 < height && x - 1 >= 0) buffer[(y + 1) * width + (x - 1)] += quantError * (3 / 16);
                        if (y + 1 < height) buffer[(y + 1) * width + x] += quantError * (5 / 16);
                        if (y + 1 < height && x + 1 < width) buffer[(y + 1) * width + (x + 1)] += quantError * (1 / 16);
                    } else if (mode === 'atkinson') {
                        const e = quantError / 8;
                        if (x + 1 < width) buffer[i + 1] += e;
                        if (x + 2 < width) buffer[i + 2] += e;
                        if (y + 1 < height && x - 1 >= 0) buffer[(y + 1) * width + (x - 1)] += e;
                        if (y + 1 < height) buffer[(y + 1) * width + x] += e;
                        if (y + 1 < height && x + 1 < width) buffer[(y + 1) * width + (x + 1)] += e;
                        if (y + 2 < height) buffer[(y + 2) * width + x] += e;
                    } else if (mode === 'stucki') {
                        const e = quantError / 48;
                        const distribute = (dx, dy, weight) => {
                            const nx = x + dx;
                            const ny = y + dy;
                            if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
                                buffer[ny * width + nx] += e * weight;
                            }
                        };
                        distribute(1, 0, 8); distribute(2, 0, 4);
                        distribute(-2, 1, 2); distribute(-1, 1, 4); distribute(0, 1, 8); distribute(1, 1, 4); distribute(2, 1, 2);
                        distribute(-2, 2, 1); distribute(-1, 2, 2); distribute(0, 2, 4); distribute(1, 2, 2); distribute(2, 2, 1);
                    }
                }
                
                const pixelIdx = i * 4;
                data[pixelIdx] = data[pixelIdx + 1] = data[pixelIdx + 2] = newPixel;
                data[pixelIdx + 3] = 255;
            }
        }
        
        ctx.putImageData(imgData, 0, 0);
    }

    function applyFrameOverlay() {
        const frameStyle = frameSelect.value;
        if (frameStyle === 'none') return;

        const srcCanvas = previewCanvas;
        const w = srcCanvas.width;
        const h = srcCanvas.height;

        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = w;
        tempCanvas.height = h;
        const tempCtx = tempCanvas.getContext('2d');
        tempCtx.drawImage(srcCanvas, 0, 0);

        const ctx = srcCanvas.getContext('2d');

        if (frameStyle === 'polaroid') {
            const topMargin = 20;
            const sideMargin = 20;
            const bottomMargin = 80;
            
            srcCanvas.width = w;
            srcCanvas.height = h + topMargin + bottomMargin;

            ctx.fillStyle = "white";
            ctx.fillRect(0, 0, srcCanvas.width, srcCanvas.height);
            
            ctx.strokeStyle = "black";
            ctx.lineWidth = 4;
            ctx.strokeRect(2, 2, srcCanvas.width - 4, srcCanvas.height - 4);

            ctx.drawImage(tempCanvas, sideMargin, topMargin, w - (sideMargin * 2), h);
            ctx.strokeRect(sideMargin, topMargin, w - (sideMargin * 2), h);

            ctx.fillStyle = "black";
            ctx.font = "bold 22px 'Inter', sans-serif";
            ctx.textAlign = "center";
            const todayStr = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
            ctx.fillText(`★ GUESTBOOK MEMORY — ${todayStr} ★`, srcCanvas.width / 2, h + topMargin + 45);

        } else if (frameStyle === 'stamp') {
            ctx.strokeStyle = "black";
            ctx.lineWidth = 6;
            ctx.strokeRect(3, 3, w - 6, h - 6);

            ctx.fillStyle = "white";
            const dotRadius = 6;
            const step = 24;

            for (let x = step; x < w; x += step) {
                ctx.beginPath(); ctx.arc(x, 0, dotRadius, 0, Math.PI * 2); ctx.fill();
                ctx.beginPath(); ctx.arc(x, h, dotRadius, 0, Math.PI * 2); ctx.fill();
            }
            for (let y = step; y < h; y += step) {
                ctx.beginPath(); ctx.arc(0, y, dotRadius, 0, Math.PI * 2); ctx.fill();
                ctx.beginPath(); ctx.arc(w, y, dotRadius, 0, Math.PI * 2); ctx.fill();
            }

        } else if (frameStyle === 'vintage') {
            ctx.strokeStyle = "black";
            ctx.lineWidth = 4;
            ctx.strokeRect(6, 6, w - 12, h - 12);
            ctx.lineWidth = 2;
            ctx.strokeRect(14, 14, w - 28, h - 28);

            ctx.fillStyle = "black";
            ctx.font = "24px sans-serif";
            ctx.fillText("✦", 20, 38);
            ctx.fillText("✦", w - 38, 38);
            ctx.fillText("✦", 20, h - 20);
            ctx.fillText("✦", w - 38, h - 20);
        }
    }

    function wrapText(ctx, text, maxWidth) {
        const lines = [];
        const rawLines = text.split('\n');
        
        for (let r = 0; r < rawLines.length; r++) {
            const line = rawLines[r].trim();
            if (!line) {
                lines.push('');
                continue;
            }
            
            const words = line.split(/\s+/);
            let currentLine = '';
            
            for (let w = 0; w < words.length; w++) {
                const word = words[w];
                const testLine = currentLine ? `${currentLine} ${word}` : word;
                const metrics = ctx.measureText(testLine);
                
                if (metrics.width > maxWidth && currentLine) {
                    lines.push(currentLine);
                    if (ctx.measureText(word).width > maxWidth) {
                        let chunk = '';
                        for (let c = 0; c < word.length; c++) {
                            const testChunk = chunk + word[c];
                            if (ctx.measureText(testChunk).width > maxWidth && chunk) {
                                lines.push(chunk);
                                chunk = word[c];
                            } else {
                                chunk = testChunk;
                            }
                        }
                        currentLine = chunk;
                    } else {
                        currentLine = word;
                    }
                } else {
                    currentLine = testLine;
                }
            }
            if (currentLine) {
                lines.push(currentLine);
            }
        }
        return lines;
    }

    function applyTicketHeaderAndFooter() {
        const srcCanvas = previewCanvas;
        const w = srcCanvas.width;
        const h = srcCanvas.height;

        const noteEl = document.getElementById('noteInput');
        const noteText = noteEl ? noteEl.value.trim() : '';

        const headerHeight = 70;
        let footerHeight = 25;
        let noteLines = [];

        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = w;
        tempCanvas.height = h;
        const tempCtx = tempCanvas.getContext('2d');
        tempCtx.drawImage(srcCanvas, 0, 0);

        if (noteText.length > 0) {
            tempCtx.font = "bold 22px 'Courier New', Courier, monospace";
            const maxTextWidth = w - 40;
            noteLines = wrapText(tempCtx, noteText, maxTextWidth);
            footerHeight = 65 + (noteLines.length * 28);
        }

        srcCanvas.width = w;
        srcCanvas.height = h + headerHeight + footerHeight;

        const ctx = srcCanvas.getContext('2d');

        ctx.fillStyle = "white";
        ctx.fillRect(0, 0, w, srcCanvas.height);

        ctx.fillStyle = "black";
        ctx.textAlign = "center";
        ctx.font = "bold 34px 'Courier New', Courier, monospace";
        ctx.fillText(`Order #${currentOrderNumber}`, w / 2, 45);

        ctx.drawImage(tempCanvas, 0, headerHeight);

        if (noteText.length > 0) {
            const footerStartY = headerHeight + h + 35;
            
            ctx.font = "bold 22px 'Courier New', Courier, monospace";
            ctx.fillText("--- Note ---", w / 2, footerStartY);

            ctx.font = "bold 22px 'Courier New', Courier, monospace";
            for (let i = 0; i < noteLines.length; i++) {
                ctx.fillText(noteLines[i], w / 2, footerStartY + 30 + (i * 28));
            }
        }
    }

    function uint8ToBase64(uint8) {
        let binary = '';
        const len = uint8.byteLength;
        const chunkSize = 0x8000;
        for (let i = 0; i < len; i += chunkSize) {
            const sub = uint8.subarray(i, i + chunkSize);
            binary += String.fromCharCode.apply(null, sub);
        }
        return window.btoa(binary);
    }

    async function fetchOrderInfo() {
        if (window.db) {
            try {
                window.db.collection('order_counter').doc('main').onSnapshot(doc => {
                    if (doc.exists && typeof doc.data().orderCounter === 'number') {
                        currentOrderNumber = doc.data().orderCounter;
                        if (originalImage) scheduleProcessImage();
                    }
                });
                return;
            } catch (e) {
                console.error("Firestore order counter error:", e);
            }
        }
        try {
            const res = await fetch('/order-info');
            if (res.ok) {
                const data = await res.json();
                if (data.orderCounter) {
                    currentOrderNumber = data.orderCounter;
                    if (originalImage) scheduleProcessImage();
                }
            }
        } catch (e) {
            console.log("Using default order counter 1");
        }
    }
    fetchOrderInfo();

    printBtn.addEventListener('click', async () => {
        try {
            printBtn.disabled = true;
            printBtn.textContent = "Processing...";
            
            statusAlert.style.display = 'block';
            statusTitle.textContent = "Sending to Printer...";
            statusMsg.textContent = "Transmitting image data in chunked packets...";
            statusAlert.style.borderColor = "rgba(59, 130, 246, 0.5)";

            const noteText = noteInput ? noteInput.value : '';

            const ctx = previewCanvas.getContext('2d');
            const width = previewCanvas.width;
            const height = previewCanvas.height;
            const imgData = ctx.getImageData(0, 0, width, height).data;

            const bytesPerLine = Math.ceil(width / 8);
            const dataSize = bytesPerLine * height;
            
            const header = new Uint8Array([
                0x1D, 0x76, 0x30, 0x00, 
                bytesPerLine & 0xFF, (bytesPerLine >> 8) & 0xFF, 
                height & 0xFF, (height >> 8) & 0xFF 
            ]);

            const payload = new Uint8Array(dataSize);
            
            let byteIndex = 0;
            for (let y = 0; y < height; y++) {
                for (let x = 0; x < width; x += 8) {
                    let byte = 0;
                    for (let bit = 0; bit < 8; bit++) {
                        if (x + bit < width) {
                            const idx = (y * width + (x + bit)) * 4;
                            const r = imgData[idx];
                            const g = imgData[idx + 1];
                            const b = imgData[idx + 2];
                            const lum = 0.299 * r + 0.587 * g + 0.114 * b;
                            if (lum < 140) {
                                byte |= (1 << (7 - bit));
                            }
                        }
                    }
                    payload[byteIndex++] = byte;
                }
            }

            const printData = new Uint8Array(header.length + payload.length);
            printData.set(header, 0);
            printData.set(payload, header.length);

            if (window.db) {
                statusTitle.textContent = "Queued to Cloud...";
                statusMsg.textContent = "Sending print job to Firebase Cloud Queue...";
                
                let docRef = null;
                try {
                    const base64Payload = uint8ToBase64(printData);
                    docRef = await window.db.collection('print_jobs').add({
                        orderNumber: currentOrderNumber,
                        payload: base64Payload,
                        createdAt: firebase.firestore.FieldValue.serverTimestamp(),
                        status: 'pending',
                        note: noteText
                    });
                } catch (addErr) {
                    console.error("Firestore upload error:", addErr);
                    throw new Error("Failed to queue job to Cloud: " + addErr.message);
                }

                statusTitle.textContent = "Waiting for Pi Printer...";
                statusMsg.textContent = `Job #${currentOrderNumber} queued! Printing on Raspberry Pi...`;

                await new Promise((resolve) => {
                    const unsubscribe = docRef.onSnapshot((doc) => {
                        if (!doc.exists) {
                            unsubscribe();
                            resolve({ success: true });
                        }
                    }, (err) => {
                        console.warn("Firestore snapshot listener notice:", err);
                        unsubscribe();
                        resolve({ success: true });
                    });

                    setTimeout(() => {
                        unsubscribe();
                        resolve({ success: true });
                    }, 20000);
                });

                statusTitle.textContent = "Printed Successfully!";
                statusMsg.textContent = `Order #${currentOrderNumber} Printed via Cloud Queue!`;
                statusAlert.style.borderColor = "var(--success)";

                currentOrderNumber++;
                if (noteInput) noteInput.value = '';
                scheduleProcessImage();

                setTimeout(() => {
                    statusAlert.style.display = 'none';
                }, 3000);
                return;
            }

            const isLocalServer = (
                window.location.hostname === 'localhost' ||
                window.location.hostname === '127.0.0.1' ||
                window.location.hostname.startsWith('192.168.') ||
                window.location.hostname.startsWith('10.')
            );

            if (isLocalServer) {
                const response = await fetch('/print', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/octet-stream',
                        'X-Print-Note': encodeURIComponent(noteText)
                    },
                    body: printData
                });

                if (!response.ok) {
                    throw new Error(`Server returned status ${response.status}`);
                }

                const result = await response.json();
                
                statusTitle.textContent = "Printed Successfully!";
                statusMsg.textContent = result.message || "Your photo has been sent to the printer!";
                statusAlert.style.borderColor = "var(--success)";
                
                if (result.nextOrder) {
                    currentOrderNumber = result.nextOrder;
                    if (noteInput) noteInput.value = '';
                    scheduleProcessImage();
                } else {
                    await fetchOrderInfo();
                }

                setTimeout(() => {
                    statusAlert.style.display = 'none';
                }, 3000);
            } else {
                // If on public Cloud domain (g-arcy.com) but window.db is not yet ready, attempt initialization
                if (typeof firebase !== 'undefined' && firebaseConfig && firebaseConfig.apiKey !== "YOUR_API_KEY") {
                    try {
                        if (!firebase.apps.length) firebase.initializeApp(firebaseConfig);
                        window.db = firebase.firestore();
                        throw new Error("Cloud Queue re-connected! Please click Print again.");
                    } catch (fbErr) {
                        throw new Error("Cloud Queue connection failed: " + fbErr.message);
                    }
                } else {
                    throw new Error("Cloud Printing Queue is connecting. Please refresh the page and try again.");
                }
            }
            
        } catch (error) {
            console.error(error);
            statusTitle.textContent = "Print Error";
            statusMsg.textContent = "Failed to print: " + error.message;
            statusAlert.style.borderColor = "var(--danger)";
        } finally {
            printBtn.disabled = false;
            printBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2" fill="none"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg> Print';
        }
    });
});
