# 🍄 AI-Based Smart Monitoring System for Oyster Mushroom Cultivation

**Author:** Brian Otieno Odhiambo  
**Supervisor:** Fredrick Omondi  
**Organization:** Japesa Farms & Agriculture Ltd  
**Course:** Bachelor of Science in Data Science  

---

## 📖 Overview
The **AI-Based Smart Monitoring System** is an end-to-end IoT and Machine Learning solution designed to modernize oyster mushroom farming. By combining real-time environmental sensors, computer vision, and cloud databases, this system empowers farmers to transition from manual, error-prone inspection to automated, data-driven farm management.

---

## ❗ The Problem It Solves
Oyster mushrooms are highly sensitive to their environment. Traditional farming methods rely heavily on manual checks, which lead to several critical issues:
* **Late Detection:** Contamination (like mold) is often discovered too late, resulting in massive yield losses.
* **Inconsistent Monitoring:** Manual temperature and humidity checks are tedious and prone to human error.
* **Lack of Data:** Without historical data, farmers cannot identify trends or optimize growing conditions over time.

**Our Solution:** This system automates the monitoring process. It continuously tracks temperature and humidity, uses AI to detect early signs of contamination via camera images, and alerts the farmer immediately before losses occur.

---

## 🛠️ Technologies Used
This project utilizes a modern, scalable tech stack:

* **Hardware/IoT:** ESP32 Microcontroller, DHT22 Temperature & Humidity Sensor, Camera Module
* **Backend & Database:** Python, Flask, Firebase Realtime Database (Cloud)
* **Machine Learning:** TensorFlow, Keras, OpenCV (Convolutional Neural Networks for image classification)
* **Frontend / Dashboard:** Streamlit, Plotly, Pandas
* **Notifications:** Twilio API (SMS), SMTP (Email)

---

## ⚙️ Features
* **Real-time Environmental Monitoring:** Live tracking of temperature and humidity.
* **AI Contamination Detection:** Upload a photo of a mushroom bag, and the AI will classify it as Healthy, Suspect, or Contaminated.
* **Automated Alerts:** Instant SMS and Email notifications when temperature spikes, humidity drops, or contamination is detected.
* **Cloud Database:** All historical data is securely logged in Firebase.
* **Interactive Dashboard:** A clean, user-friendly Streamlit interface to visualize trends and manage alerts.

---

## 🚀 How to Install and Run

Follow these steps to run the system locally on your machine.

### Prerequisites
* Python 3.10 - 3.12 installed on your system.
* A Firebase account with a Realtime Database created.
* VS Code (or any preferred IDE).

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/mushroom-system.git
cd mushroom-system
