# Cursor Account Generator  

A cleaner version of [cursor-auto-free](https://github.com/chengazhen/cursor-auto-free).  

## 🔹 Differences  
- **Email Handling**: Supports automatic temp mail and bring-your-own-mailserver. 
- **Captcha Handling**: Requires **manual** Turnstile Captcha validation (twice).  

## 🔹 Requirements  
Ensure you have the following installed before running the script:  
- **Cursor** (obviously)  
- **Google Chrome** (or any other browser compatible with `zendriver`)  
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**  

---

## 🚀 Usage  

### 1️⃣ Configure Environment  
Copy the example configuration file:  
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
- Ensure `postfix-regexp.cf` rules capture emails sent to addresses following `{EMAIL_ADDRESS_PREFIX}{random_letters}@DOMAIN`. So, if your domain is `example.com`, and your EMAIL_ADDRESS_PREFIX is `cur`, then the line should be: `/^cur[a-zA-Z0-9]*@example.com/ centralised-email@example.com`

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
It will then start the browser and begin the signup process.

You will need to **manually click on the Turnstile Captcha twice**.

After that is done, the sign up process will be completed automatically.

---

## ⚠️ Warning  
- This script is **not affiliated with Cursor or its developers**.  
- It **modifies your system registry and file system**—use with caution.  
- The author is **not responsible** for any system damage or service-related issues.  
- This script is provided **for educational purposes only**.