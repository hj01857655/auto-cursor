# Cursor Account Generator  

A cleaner version of [cursor-auto-free](https://github.com/chengazhen/cursor-auto-free).  

## 🔹 Differences  
- **Email Handling**: Supports automatic temp-mail, Cloudflare email proxying and bring-your-own-mailserver. 
- **Captcha Handling**: Requires **manual** Turnstile Captcha validation (twice).  

## 🔹 Requirements  
Ensure you have the following installed before running the script:  
- **Cursor** (obviously)  
- **Google Chrome** (or any other browser compatible with `zendriver`)  
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**  

---

## 🚀 Usage  

### 1️⃣ Configure Environment  
Copy the example configuration file and update it with your email domain and IMAP details:  
```bash
cp .env.example .env
```

### 2️⃣ Choose a Method  

#### **Method 1 (Easy but Less Reliable) – Recommended for First-Time Users**  
- In `.env`, set:  
  ```env
  USE_TEMPMAIL=True
  ```
- Leave the other fields **empty**.  

#### **Method 2 (Harder but More Reliable)**  
- In `.env`, set:
  ```env
  USE_TEMPMAIL=False
  ```
- Provide **IMAP credentials** of your self-hosted mail server.  
- Ensure `postfix-regex.cf` rules capture emails sent to addresses following `{EMAIL_ADDRESS_PREFIX}{random_letters}@DOMAIN`.  

---

### 3️⃣ Install Dependencies  
Run the following command:  
```bash
uv sync
```

### 4️⃣ Run the Script  
Once setup is complete, start the script using:  
```bash
uv run main.py
```

---

## ⚠️ Warning  
- This script is **not affiliated with Cursor or its developers**.  
- It **modifies your system registry and file system**—use with caution.  
- The author is **not responsible** for any system damage or service-related issues.  
- This script is provided **for educational purposes only**.