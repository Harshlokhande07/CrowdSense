# 🔒 CrowdSense — Privacy & Ethical AI Architecture

CrowdSense is built from the ground up to protect individual civil liberties, privacy, and data protection rights in public and private event spaces.

---

## 🛡️ Core Privacy Principles

### 1. Zero Facial Recognition & Zero Biometric Profiling
* CrowdSense **does not perform face detection, facial recognition, facial landmarking, or emotion analysis**.
* The computer-vision pipeline is restricted strictly to full-body person bounding boxes (COCO Class 0: `person`) used exclusively to estimate ground contact coordinates $(c_x, y_2)$ and spatial density.

### 2. Ephemeral & Anonymous Tracking
* Object tracking identifiers (`track_id`) are transient integer IDs generated in-memory during active tracking sequences.
* Track IDs carry no persistent biometric signatures, cross-camera person re-identification (ReID), or longitudinal tracking data.

### 3. No Persistent Raw Video Storage by Default
* Video streams are processed in-memory in volatile RAM buffers.
* Raw video frames and camera feeds are **not saved, recorded, or transmitted to cloud servers** unless explicit manual video upload is triggered by an authorized operator for forensic playback.

### 4. Aggregate Spatial Telemetry Only
* Outgoing WebSocket telemetry broadcasts spatial aggregates (e.g. $8 \times 8$ grid counts, velocity vectors, zone density per $m^2$, and composite risk scores).
* Telemetry contains zero personally identifiable information (PII).

### 5. Regulatory Compliance
CrowdSense is designed to assist venue safety operators while remaining compliant with:
* **GDPR (General Data Protection Regulation)**: Purpose limitation, data minimization, and privacy by design (Articles 5 & 25).
* **CCPA / CPRA**: No sale or sharing of personal biometric consumer data.
* **EU AI Act**: Designed as an early-warning safety support tool requiring human-in-the-loop verification prior to crowd control intervention.
