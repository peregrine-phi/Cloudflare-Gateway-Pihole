![CF_logo_stacked_whitetype](https://github.com/luxysiv/Cloudflare-Gateway-Pihole/assets/46205571/b8b7b12b-2fd8-4978-8e3c-2472a4167acb)

### Cập nhật mới

* Nếu nhận được e-mail kêu bị dừng Github Action, đừng lo lắng, Github Action sẽ tiếp tục chạy mãi mãi hoặc [Cài thời gian script tự động chạy](#cai-thoi-gian-script-tu-dong-chay)

* Logic mới, sẽ cập nhật chính xác tên miền thay đổi, không gây thiệt hại lên máy chủ Cloudflare, có thể chạy cron hàng giờ

* Các bạn phải xoá các danh sách được tải lên bởi script khác để tạo số danh sách trống

* Đừng quan tâm đến số danh sách được tạo ra bởi script.

* Thêm danh sách trắng riêng ở [Cloudflare-Gateway-Allow](https://github.com/luxysiv/Cloudflare-Gateway-Allow)...

### Cài thời gian script tự động chạy 
---
> Sử dụng Cloudflare Workers để chạy Github Action. Không lo sau 2 tháng Github tắt Action.Tạo Github Token không hết hạn với quyền truy cập workflow là đủ.
```javascript
addEventListener('scheduled', event => {
  event.waitUntil(handleScheduledEvent());
});

async function handleScheduledEvent() {
  // --- CONFIGURATION ---
  const GITHUB_TOKEN = 'YOUR_GITHUB_TOKEN_HERE';
  const GITHUB_USER  = 'YOUR_USER_NAME';
  const GITHUB_REPO  = 'YOUR_REPO_NAME';
  const WORKFLOW_ID  = 'main.yml'; 
  // ---------------------

  const url = `https://api.github.com/repos/${GITHUB_USER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_ID}/dispatches`;

  try {
    const dispatchResponse = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${GITHUB_TOKEN}`,
        'Content-Type': 'application/json',
        'User-Agent': 'Cloudflare-Worker-Trigger',
      },
      body: JSON.stringify({
        ref: 'main'
      }),
    });

    if (!dispatchResponse.ok) {
      const errorText = await dispatchResponse.text();
      throw new Error(`Status: ${dispatchResponse.status} - ${errorText}`);
    }
    console.log('Successfully dispatched GitHub Action');
  } catch (error) {
    console.error('Error handling scheduled event:', error);
  }
}

```
Nhớ cài cron trigger cho Cloudflare Workers 


### Dành cho các bạn Việt Nam
---
Các bạn cần phân biệt `bộ lọc DNS` và `bộ lọc browser`. Mình thấy nhiều bạn đem `bộ lọc browser` lên chạy -> lỗi lướt web

### Hướng dẫn sử dụng
---
Thêm `Variables Secrets` vào 
`https://github.com/your-user/your-repository/settings/secrets/actions`:

* `CF_IDENTIFIER` được lấy từ tài khoản CF của bạn (dãy ký tự ngay sau `https://dash.cloudflare.com/`: **https://dash.cloudflare.com/?to=/:account/workers**

* `CF_API_TOKEN` lấy từ : **https://dash.cloudflare.com/profile/api-tokens** với `3 permissions`
   1. `Account.Zero Trust : Edit` 
   2. `Account.Account Firewall Access Rules : Edit`
   3. `Account.Access: Apps and Policies : Edit`

hoặc có thể thêm vào **[.env](../.env)** ( **không khuyến khích** )

`Secret Github Action` giống như sau:
![1000015672](https://github.com/luxysiv/Cloudflare-Gateway-Pihole/assets/46205571/6bd7f41d-0ca5-4944-95d3-d41dfd913c60)

Tạo `CF_API_TOKEN` giống như sau:
![CF_API_TOKEN](https://github.com/luxysiv/Cloudflare-Gateway-Pihole/assets/46205571/a5b90438-26cc-49ae-9a55-5409a90b683f)

### Chú ý  
---
* `Giới hạn` của `Cloudflare Gateway Zero Trust` (gói miễn phí) là **300 danh sách × 1.000 mục**, tức khoảng **300k tên miền**. Script sẽ kiểm tra `MAX_GATEWAY_DOMAINS` và `MAX_GATEWAY_LISTS` (mặc định 300) trước khi tải lên và dừng nếu vượt quá.

* Các bạn đã tải các danh sách bộ lọc bằng script khác thì nên xoá đi bằng tính năng xoá của script đã up hoặc xoá tay

* Mình đã update thêm tính năng xoá danh sách khi các bạn không muốn sử dụng script nữa. Vào **[main.yml](../.github/workflows/main.yml)** để như sau:

```yml
      - name: Cloudflare Gateway Zero Trust 
        run: python -m src leave
```

* Hỗ trợ **[dynamic_blacklist.txt](../lists/dynamic_blacklist.txt)** và **[dynamic_whitelist.txt](../lists/dynamic_whitelist.txt)** để các bạn tự `chặn` hoặc `bỏ chặn` tên miền theo ý thích

* Hỗ trợ thêm `chặn` và `bỏ chặn` trong `Github Actions variables `. Định dạng giống như **[dynamic_blacklist.txt](../lists/dynamic_blacklist.txt)** và **[dynamic_whitelist.txt](../lists/dynamic_whitelist.txt)** ở `Value*`. `DYNAMIC_BLACKLIST` và `DYNAMIC_WHITELIST` cho `Name*`

* Thêm danh sách `chặn` của bạn vào **[adlist.ini](../lists/adlist.ini)** và `loại bỏ chặn` ở **[whitelist.ini](../lists/whitelist.ini)**

* Đã hỗ trợ 2 loại định dạng danh sách 

```ini
https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt
```
hoặc
```ini
[Ad-Urls]
Adguard = https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt
```
* Bạn nên thêm danh sách tùy chỉnh vào `Action variables` như sau
> Name:
  >> `ADLIST_URLS` hoặc `WHITELIST_URLS`.

  > Value: `danh sách các URLs`
  >> Ví dụ:
  ```text
  https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt
  https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/light-onlydomains.txt
  ```

👌 Chúc các bạn thành công 

👌 Mọi thắc mắc về script các bạn có thể mở issue
