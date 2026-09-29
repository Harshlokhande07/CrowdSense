# 🔒 CrowdSense — Privacy & Ethical AI Architecture

CrowdSense is engineered with privacy-by-design principles to protect individual civil liberties, anonymity, and data protection rights in public and private event spaces.

---

## 🛡️ Core Privacy Principles

### 1. Zero Facial Recognition & Zero Biometric Profiling
* CrowdSense **does not perform face detection, facial recognition, facial landmarking, iris scanning, or emotion analysis**.
* The computer-vision pipeline is restricted strictly to full-body person bounding boxes (COCO Class 0: `person`) used exclusively to estimate ground contact coordinates $(c_x, y_2)$ and spatial density.

### 2. Ephemeral & Anonymous Tracking
* Object tracking identifiers (`track_id`) are transient integer IDs generated in-memory during active tracking sequences.
* Track IDs carry no persistent biometric signatures, cross-camera person re-identification (ReID), or longitudinal tracking data.
* All track state is completely cleared on camera switch, restart, or stream reset.

### 3. Zero Persistent Raw Video Frames
* Video streams are processed strictly in-memory in volatile RAM buffers.
* Raw video frames and camera feeds are **never saved, recorded, or persisted to disk or cloud storage** during live monitoring.
* Temporary clip uploads for forensic simulation in development are automatically purged from local disk (`scratch/uploads/`).

### 4. Mobile & Local Webcam Privacy Architecture
* **Local Laptop Webcam**: Webcam frames captured by CrowdSense are processed strictly in volatile RAM memory and are **never recorded, cached, or written to disk**.
* **Clean Device Release**: When the camera is toggled OFF (or the server is stopped), the hardware capture device is released immediately (`cap.release()`), ensuring the physical camera indicator LED turns off and the webcam is freed for other system applications.
* **Honest On-Screen Indication**: The dashboard interface provides a clear, real-time indicator (`CAMERA ON` / `CAMERA OFF`, with status dot) reflecting the exact physical state of the camera.
* **Mobile Camera Streaming**: When using a mobile device, camera frames stream over an encrypted WebSocket (`wss://`) and are processed in volatile RAM with zero disk writes.
* **Informed Notice**: In accordance with privacy and surveillance standards, operators deploying local laptop or mobile cameras in workplaces or public event spaces should inform individuals within view with prominent signage.

### 5. Aggregate Spatial Telemetry Only
* Outgoing WebSocket telemetry broadcasts spatial aggregates (e.g. $8 \times 8$ grid counts, velocity vectors, zone density per $m^2$, and composite risk scores).
* Telemetry contains zero personally identifiable information (PII).

### 6. Third-Party Notification Data Minimization
* **Twilio SMS / WhatsApp**: Dispatches only zone name, camera label, risk level, risk score, and timestamp. Zero images, video frames, or tracking boxes are sent.
* **ntfy.sh / Push Notifications**: Dispatches only concise text alert summaries.
* **Firestore Incident Log**: Stores only timestamped alert metadata (incident ID, severity, zone ID, resolution notes, and timestamps).

### 7. Regulatory Compliance
* **Digital Personal Data Protection (DPDP) Act 2023 (India)**: Complies with purpose limitation and strict minimization of visual data processing.
* **GDPR (General Data Protection Regulation, EU)**: Implements Data Minimisation (Article 5(1)(c)), Storage Limitation (Article 5(1)(e)), and Privacy by Design (Article 25).
* **EU AI Act**: Classified as an early-warning safety support tool requiring human-in-the-loop verification prior to any operational crowd intervention.

---

## 📋 Data Retention Guidance

| Data Category | Storage Location | Retention Period | PII Present |
|---|---|---|---|
| Live Video Frames (CCTV & Mobile) | Volatile RAM only | 0s (Discarded immediately after frame inference) | None (In-memory only) |
| Active Tracks | Volatile RAM only | Duration of continuous track in frame | None (Anonymous integer ID) |
| Incident Event Logs | In-memory / Firestore | 30–90 days (Configurable by venue compliance policy) | None (Zone metadata only) |
| SMS / WhatsApp Notifications | Twilio Gateway Logs | Managed per venue Twilio account retention policy | Masked phone numbers |
