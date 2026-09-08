Bisa. Ini aku buat sebagai **panduan user lengkap** khusus setup `new-api-bootstrap` kita, jadi nanti kalau lupa tinggal ikuti urutannya.

# Panduan Mengubah Isi Model Combo `coding`

## 1. Pahami cara kerja combo

Dalam setup kita, `coding` bukan model asli. `coding` adalah **alias model** yang tersedia pada beberapa channel.

Saat ini:

```text
coding
├── MiniMax-All-Free-Xkiro
│   └── coding → minimax/minimax-m3:free
│
├── Mistral-All-Free-Xkiro
│   └── coding → mistralai/codestral-2508
│
└── DeepSeek-All-Free-Xkiro
    └── coding → deepseek/deepseek-v4-pro
```

Jadi ketika OpenCode/Hermes mengirim:

```json
"model": "coding"
```

New API memilih salah satu channel yang menyediakan `coding`, kemudian `model_mapping` menerjemahkannya menjadi model upstream sebenarnya.

---

# A. MENAMBAHKAN MODEL KE COMBO

Misalnya kita ingin memasukkan:

```text
minimax/minimax-m3:free
```

ke combo `coding`.

## 2. Edit channel di New API

Buka:

```text
New API
→ Channel
→ pilih channel yang modelnya ingin dimasukkan
→ Edit
```

Contohnya:

```text
MiniMax-All-Free-Xkiro
```

### Models

Model upstream yang ingin disembunyikan:

```text
minimax/minimax-m3:free
```

diganti menjadi:

```text
coding
```

Misalnya sebelumnya:

```text
minimax/minimax-m3:free
minimax/minimax-m2.7:free
minimax/minimax-m2.5:free
```

menjadi:

```text
coding
minimax/minimax-m2.7:free
minimax/minimax-m2.5:free
```

**Jangan biarkan `coding` dan `minimax/minimax-m3:free` sama-sama berada di Models** untuk pola combo kita.

---

## 3. Tambahkan Model Mapping

Pada bagian **Model Mapping**, masukkan:

```json
{
  "coding": "minimax/minimax-m3:free"
}
```

Artinya:

```text
Client meminta:
coding

        ↓ New API mapping

Provider menerima:
minimax/minimax-m3:free
```

Kemudian save channel.

---

## 4. Atur routing combo

Kalau ingin semua anggota `coding` berada pada tingkat routing yang sama, gunakan misalnya:

```text
Priority: 0
Weight:   1
```

Untuk ketiga channel:

```text
MiniMax     priority 0 / weight 1
Mistral     priority 0 / weight 1
DeepSeek    priority 0 / weight 1
```

Dengan begitu ketiganya eligible untuk menangani `coding`.

---

# B. UPDATE `channels.json`

Ini **wajib dilakukan** untuk setup bootstrap kita.

Walaupun perubahan di UI New API sudah bekerja, file:

```text
~/Projects/new-api-bootstrap/config/channels.json
```

adalah source-of-truth bootstrap kita.

Kalau tidak diperbarui, `sync_channels.sh --apply` nantinya bisa mengembalikan perubahan manualmu.

## 5. Masuk ke project

```fish
cd ~/Projects/new-api-bootstrap
```

Buka:

```fish
nano config/channels.json
```

Cari channel yang tadi diubah.

Contoh:

```json
{
  "name": "MiniMax-All-Free-Xkiro",
  "provider": "xkiro",
  "type": "openai",
  "base_url": "https://api.xkiro.com",
  "api_key_env": "XKIRO_API_KEY",

  "models": [
    "coding",
    "minimax/minimax-m2.7:free",
    "minimax/minimax-m2.5:free"
  ],

  "model_mapping": {
    "coding": "minimax/minimax-m3:free"
  },

  "group": "default",
  "priority": 0,
  "weight": 1,
  "auto_ban": true
}
```

Konsep terpentingnya cuma dua:

```json
"models": [
  "coding"
]
```

dan:

```json
"model_mapping": {
  "coding": "minimax/minimax-m3:free"
}
```

---

# C. VALIDASI DAN SYNC

## 6. Cek JSON

Sebelum sync, pastikan JSON tidak rusak:

```fish
jq empty config/channels.json
```

Kalau **tidak mengeluarkan apa-apa**, JSON valid.

Kalau ada error seperti:

```text
parse error...
```

jangan jalankan `--apply` dulu. Perbaiki JSON-nya.

---

## 7. Dry-run dulu

Jalankan:

```fish
./scripts/sync_channels.sh
```

Ini tidak melakukan perubahan karena bootstrap kita default-nya dry-run.

Misalnya kalau UI dan JSON berbeda:

```text
[UPDATE] MiniMax-All-Free-Xkiro
[SKIP]   Mistral-All-Free-Xkiro
[SKIP]   DeepSeek-All-Free-Xkiro

Create : 0
Update : 1
Skip   : 8
```

Periksa apakah perubahan yang terdeteksi memang sesuai keinginan.

---

## 8. Apply

Kalau sudah benar:

```fish
./scripts/sync_channels.sh --apply
```

Setelah selesai, jalankan lagi:

```fish
./scripts/sync_channels.sh
```

Kondisi ideal:

```text
Create : 0
Update : 0
Skip   : 9
Total  : 9
```

Artinya:

```text
channels.json
     =
New API
```

sudah sinkron.

---

# D. CEK ISI COMBO

Kita sudah membuat command:

```fish
newapi-coding
```

Jalankan:

```fish
newapi-coding
```

Contoh output:

```text
MiniMax-All-Free-Xkiro → minimax/minimax-m3:free
Mistral-All-Free-Xkiro → mistralai/codestral-2508
DeepSeek-All-Free-Xkiro → deepseek/deepseek-v4-pro
```

Ini adalah cara tercepat mengecek **kondisi aktual combo di New API**.

Bukan:

```fish
newapi-models
```

karena command tersebut menampilkan semua model publik New API.

Bedanya:

```text
newapi-models
→ semua model yang dapat diakses client

newapi-coding
→ upstream model yang tergabung dalam combo coding
```

---

# E. MENGGANTI MODEL DALAM COMBO

Misalnya sekarang:

```text
coding → minimax/minimax-m3:free
```

mau diganti menjadi:

```text
coding → minimax/minimax-m2.7:free
```

### Di New API

Ubah mapping:

```json
{
  "coding": "minimax/minimax-m2.7:free"
}
```

Kemudian pastikan `Models`:

```text
coding
```

dan model yang sekarang menjadi target mapping tidak perlu diekspos sebagai model publik pada channel tersebut untuk pola combo kita.

### Di `channels.json`

Ubah:

```json
"model_mapping": {
  "coding": "minimax/minimax-m2.7:free"
}
```

Kemudian sesuaikan `"models"` kalau diperlukan.

Lalu:

```fish
jq empty config/channels.json
./scripts/sync_channels.sh
./scripts/sync_channels.sh --apply
newapi-coding
```

---

# F. MENGHAPUS MODEL DARI COMBO

Misalnya MiniMax ingin dikeluarkan sehingga tinggal:

```text
coding
├── Codestral
└── DeepSeek V4 Pro
```

Pada channel MiniMax, hapus:

```json
"model_mapping": {
  "coding": "minimax/minimax-m3:free"
}
```

dan hapus:

```text
coding
```

dari Models.

Kalau model MiniMax tetap ingin tersedia secara individual, masukkan kembali nama aslinya:

```text
minimax/minimax-m3:free
```

Lakukan hal yang sama di:

```text
config/channels.json
```

Contohnya kembali menjadi:

```json
"models": [
  "minimax/minimax-m3:free",
  "minimax/minimax-m2.7:free"
]
```

tanpa mapping `coding`.

Kemudian sync.

---

# G. URUTAN YANG PALING AMAN

Setiap kali mau mengubah combo, biasakan workflow ini:

```text
1. Tentukan model upstream
        ↓
2. Edit Channel di New API
        ↓
3. Models: upstream → coding
        ↓
4. Model Mapping:
   coding → upstream
        ↓
5. Save & test channel
        ↓
6. Edit config/channels.json
        ↓
7. jq empty config/channels.json
        ↓
8. ./scripts/sync_channels.sh
        ↓
9. ./scripts/sync_channels.sh --apply
        ↓
10. newapi-coding
```

### Contoh hasil akhir

```text
$ newapi-coding

MiniMax-All-Free-Xkiro → minimax/minimax-m3:free
Mistral-All-Free-Xkiro → mistralai/codestral-2508
DeepSeek-All-Free-Xkiro → deepseek/deepseek-v4-pro
```

Kalau itu muncul, berarti combo sudah benar.

---

## OpenCode dan Hermes tidak perlu diedit lagi

Ini salah satu keuntungan desain kita.

OpenCode hanya mengenal:

```json
"coding": {
  "name": "Coding"
}
```

Hermes juga hanya meminta:

```text
coding
```

Jadi kamu bebas mengubah backend:

```text
Hari ini:

coding
├── MiniMax
├── Codestral
└── DeepSeek

Besok:

coding
├── Qwen
├── GLM
├── Codestral
└── DeepSeek
```

tanpa mengubah konfigurasi OpenCode atau Hermes.

**Selama nama alias tetap `coding`, client tidak perlu tahu model apa saja yang ada di belakangnya.**

Dan karena repo bootstrap-mu ada di Git, setelah perubahan combo sudah benar jangan lupa:

```fish
git add config/channels.json
git commit -m "Update coding combo models"
git push
```

Jadi konfigurasi combo terbaru juga tersimpan di GitHub, bukan hanya di New API lokal.
