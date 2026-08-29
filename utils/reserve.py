from utils import AES_Encrypt, enc, generate_captcha_key, verify_param
import json
import requests
import re
import time
import logging
import datetime
from urllib3.exceptions import InsecureRequestWarning


def get_date(day_offset: int = 0):
    today = datetime.datetime.now().date()
    offset_day = today + datetime.timedelta(days=day_offset)
    tomorrow = offset_day.strftime("%Y-%m-%d")
    return tomorrow


class reserve:
    def __init__(
        self,
        sleep_time=0.2,
        max_attempt=50,
        enable_slider=False,
        reserve_next_day=False,
    ):
        self.login_page = (
            "https://passport2.chaoxing.com/mlogin?loginType=1&newversion=true&fid="
        )
        self.url = (
            "https://office.chaoxing.com/front/third/apps/seat/code?id={}&seatNum={}"
        )
        self.submit_url = "https://office.chaoxing.com/data/apps/seat/submit"
        self.seat_url = "https://office.chaoxing.com/data/apps/seat/getusedtimes"
        self.login_url = "https://passport2.chaoxing.com/fanyalogin"
        self.token = ""
        self.success_times = 0
        self.fail_dict = []
        self.submit_msg = []
        self.requests = requests.session()
        self.token_pattern = re.compile("token = '(.*?)'")
        self.headers = {
            "Referer": "https://office.chaoxing.com/",
            "Host": "captcha.chaoxing.com",
            "Pragma": "no-cache",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }
        self.login_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "accept-encoding": "gzip, deflate, br, zstd",
            "cache-control": "no-cache",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X) AppleWebKit/603.1.3 (KHTML, like Gecko) Version/10.0 Mobile/14E304 Safari/602.1 wechatdevtools/1.05.2109131 MicroMessenger/8.0.5 Language/zh_CN webview/16364215743155638",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Host": "passport2.chaoxing.com",
        }

        self.sleep_time = sleep_time
        self.max_attempt = max_attempt
        self.enable_slider = enable_slider
        self.reserve_next_day = reserve_next_day
        self.logged_in = False
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

    def warm_up(self):
        """Warm heavy libraries and reusable HTTPS connections before login."""
        started_at = time.perf_counter()

        # The first OpenCV/Numpy import and operation is noticeably slower on a
        # fresh GitHub runner. Do it before the login-success timer starts.
        try:
            import numpy as np
            import cv2

            sample = np.zeros((32, 32), dtype=np.uint8)
            cv2.Canny(sample, 100, 200)
        except Exception as error:
            logging.warning(f"OpenCV/Numpy warm-up failed: {error}")

        # Establish DNS/TLS connections in the same Session that will be used
        # for the reservation. A failed root-page response is harmless: opening
        # the connection is the useful part of this warm-up.
        warm_urls = (
            "https://office.chaoxing.com/",
            "https://captcha.chaoxing.com/",
            "https://captcha-b.chaoxing.com/",
        )
        for url in warm_urls:
            try:
                self.requests.get(
                    url,
                    headers={"User-Agent": self.headers["User-Agent"]},
                    timeout=3,
                    verify=False,
                )
            except requests.RequestException as error:
                logging.debug(f"Connection warm-up failed for {url}: {error}")

        logging.info(
            f"Runtime and HTTPS connections warmed up in "
            f"{time.perf_counter() - started_at:.3f}s"
        )

    # login and page token
    def _get_page_token(self, url, require_value=False):
        response = self.requests.get(url=url, verify=False)
        html = response.content.decode("utf-8")
        # matches = re.findall(r"token = \'(.*?)\'", html)
        matches = re.findall(r'id="submit_enc"\s+value="(.*?)"', html)
        value_matches = None
        if require_value:
            value_matches = re.findall(r'value="(.*?)"', html)
            if not matches:
                logging.error(f"Failed to get token from {url}")
                return "", ""
            if not value_matches:
                logging.error(f"Failed to get submit value from {url}")
                return matches[0], ""
        return matches[0] if matches else "", value_matches[0] if value_matches else ""

    def get_login_status(self):
        self.requests.headers = self.login_headers
        self.requests.get(url=self.login_page, verify=False)

    def login(self, username, password):
        username = AES_Encrypt(username)
        password = AES_Encrypt(password)
        parm = {
            "fid": -1,
            "uname": username,
            "password": password,
            "refer": "http%3A%2F%2Foffice.chaoxing.com%2Ffront%2Fthird%2Fapps%2Fseat%2Fcode%3Fid%3D4219%26seatNum%3D380",
            "t": True,
        }
        jsons = self.requests.post(url=self.login_url, params=parm, verify=False)
        obj = jsons.json()
        if obj["status"]:
            self.logged_in = True
            logging.info(f"User {username} login successfully")
            return (True, "")
        else:
            self.logged_in = False
            logging.info(
                f"User {username} login failed. Please check you password and username! "
            )
            return (False, obj["msg2"])

    # extra: get roomid
    def roomid(self, encode):
        url = f"https://office.chaoxing.com/data/apps/seat/room/list?cpage=1&pageSize=100&firstLevelName=&secondLevelName=&thirdLevelName=&deptIdEnc={encode}"
        json_data = self.requests.get(url=url).content.decode("utf-8")
        ori_data = json.loads(json_data)
        for i in ori_data["data"]["seatRoomList"]:
            info = f'{i["firstLevelName"]}-{i["secondLevelName"]}-{i["thirdLevelName"]} id为：{i["id"]}'
            print(info)

    # solve captcha

    def resolve_captcha(self):
        logging.info(f"Start to resolve captcha token")
        captcha_token, bg, tp = self.get_slide_captcha_data()
        logging.info(f"Successfully get prepared captcha_token {captcha_token}")
        logging.info(f"Captcha Image URL-small {tp}, URL-big {bg}")
        x = self.x_distance(bg, tp)
        logging.info(f"Successfully calculate the captcha distance {x}")

        params = {
            "callback": "jQuery33109180509737430778_1716381333117",
            "captchaId": "42sxgHoTPTKbt0uZxPJ7ssOvtXr3ZgZ1",
            "type": "slide",
            "token": captcha_token,
            "textClickArr": json.dumps([{"x": x}]),
            "coordinate": json.dumps([]),
            "runEnv": "10",
            "version": "1.1.18",
            "_": int(time.time() * 1000),
        }
        response = self.requests.get(
            f"https://captcha.chaoxing.com/captcha/check/verification/result",
            params=params,
            headers=self.headers,
        )
        text = response.text.replace(
            "jQuery33109180509737430778_1716381333117(", ""
        ).replace(")", "")
        data = json.loads(text)
        logging.info(f"Successfully resolve the captcha token {data}")
        try:
            validate_val = json.loads(data["extraData"])["validate"]
            return validate_val
        except KeyError as e:
            logging.info("Can't load validate value. Maybe server return mistake.")
            return ""

    def get_slide_captcha_data(self):
        url = "https://captcha.chaoxing.com/captcha/get/verification/image"
        timestamp = int(time.time() * 1000)
        capture_key, token = generate_captcha_key(timestamp)
        referer = f"https://office.chaoxing.com/front/third/apps/seat/code?id=3993&seatNum=0199"
        params = {
            "callback": f"jQuery33107685004390294206_1716461324846",
            "captchaId": "42sxgHoTPTKbt0uZxPJ7ssOvtXr3ZgZ1",
            "type": "slide",
            "version": "1.1.18",
            "captchaKey": capture_key,
            "token": token,
            "referer": referer,
            "_": timestamp,
            "d": "a",
            "b": "a",
        }
        response = self.requests.get(url=url, params=params, headers=self.headers)
        content = response.text

        data = content.replace(
            "jQuery33107685004390294206_1716461324846(", ")"
        ).replace(")", "")
        data = json.loads(data)
        captcha_token = data["token"]
        bg = data["imageVerificationVo"]["shadeImage"]
        tp = data["imageVerificationVo"]["cutoutImage"]
        return captcha_token, bg, tp

    def x_distance(self, bg, tp):
        import numpy as np
        import cv2

        def cut_slide(slide):
            slider_array = np.frombuffer(slide, np.uint8)
            slider_image = cv2.imdecode(slider_array, cv2.IMREAD_UNCHANGED)
            slider_part = slider_image[:, :, :3]
            mask = slider_image[:, :, 3]
            mask[mask != 0] = 255
            x, y, w, h = cv2.boundingRect(mask)
            cropped_image = slider_part[y : y + h, x : x + w]
            return cropped_image

        c_captcha_headers = {
            "Referer": "https://office.chaoxing.com/",
            "Host": "captcha-b.chaoxing.com",
            "Pragma": "no-cache",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }
        bgc, tpc = self.requests.get(bg, headers=c_captcha_headers), self.requests.get(
            tp, headers=c_captcha_headers
        )
        bg, tp = bgc.content, tpc.content
        bg_img = cv2.imdecode(np.frombuffer(bg, np.uint8), cv2.IMREAD_COLOR)
        tp_img = cut_slide(tp)
        bg_edge = cv2.Canny(bg_img, 100, 200)
        tp_edge = cv2.Canny(tp_img, 100, 200)
        bg_pic = cv2.cvtColor(bg_edge, cv2.COLOR_GRAY2RGB)
        tp_pic = cv2.cvtColor(tp_edge, cv2.COLOR_GRAY2RGB)
        res = cv2.matchTemplate(bg_pic, tp_pic, cv2.TM_CCOEFF_NORMED)
        _, _, _, max_loc = cv2.minMaxLoc(res)
        tl = max_loc
        return tl[0]

    @staticmethod
    def _normalize_seat_ids(seatid):
        """Return an ordered, de-duplicated list of seat number strings."""
        if isinstance(seatid, str):
            seats = [seatid]
        elif isinstance(seatid, (list, tuple)):
            seats = list(seatid)
        else:
            raise TypeError("seatid must be a string, list, or tuple")

        normalized = []
        for seat in seats:
            if not isinstance(seat, str):
                raise TypeError("every seatid must be a string, for example '006'")
            seat = seat.strip()
            if seat and seat not in normalized:
                normalized.append(seat)

        if not normalized:
            raise ValueError("seatid cannot be empty")
        return normalized

    def submit(
        self,
        times,
        roomid,
        seatid,
        action,
    ):
        seats = self._normalize_seat_ids(seatid)

        logging.info(
            f"本次备选座位：{seats}"
        )

        captcha_count = 0
        max_captcha_count = len(seats)

        # 每个座位只尝试一次
        for seat_index, seat in enumerate(seats):
            logging.info(
                f"尝试座位 {seat}，"
                f"进度 {seat_index + 1}/{len(seats)}"
            )

            token, value = self._get_page_token(
                self.url.format(
                    roomid,
                    seat,
                ),
                require_value=True,
            )

            logging.info(
                f"Get token: {token}"
            )

            # 没有token时不生成验证码
            if not token or not value:
                logging.warning(
                    f"座位 {seat} 没有有效token，"
                    "跳过且不生成验证码"
                )

                if seat_index < len(seats) - 1:
                    logging.info(
                        f"等待 {self.sleep_time} 秒后"
                        "检查下一个座位"
                    )
                    time.sleep(self.sleep_time)

                continue

            captcha = ""

            if self.enable_slider:
                if captcha_count >= max_captcha_count:
                    logging.warning(
                        "已达到本轮验证码次数限制，停止"
                    )
                    break

                captcha_count += 1

                logging.info(
                    f"开始生成第 "
                    f"{captcha_count}/{max_captcha_count} "
                    "次验证码"
                )

                captcha = self.resolve_captcha()

                # 当前验证码失败，等待后尝试下一个座位
                if not captcha:
                    logging.warning(
                        f"座位 {seat} 验证码失败"
                    )

                    if seat_index < len(seats) - 1:
                        logging.info(
                            f"等待 {self.sleep_time} 秒后"
                            "尝试下一个座位"
                        )
                        time.sleep(self.sleep_time)

                    continue

            logging.info(
                f"Captcha token {captcha}"
            )

            success = self.get_submit(
                self.submit_url,
                times=times,
                token=token,
                roomid=roomid,
                seatid=seat,
                captcha=captcha,
                action=action,
                value=value,
            )

            if success:
                logging.info(
                    f"座位 {seat} 预约成功"
                )
                return True

            logging.info(
                f"座位 {seat} 预约失败"
            )

            # 还有下一个座位时才等待
            if seat_index < len(seats) - 1:
                logging.info(
                    f"等待 {self.sleep_time} 秒后"
                    "尝试下一个座位"
                )
                time.sleep(self.sleep_time)

        logging.info(
            f"三个座位均未成功，"
            f"本轮共生成 {captcha_count} 次验证码，"
            "任务结束"
        )

        return False

        logging.warning(
            "所有座位都没有获取到有效token，"
            "本次没有生成验证码"
        )

        return False

    def get_submit(
        self, url, times, token, roomid, seatid, captcha="", action=False, value=""
    ):
                # GitHub Actions 使用 UTC，先转换成北京时间日期
        if action:
            beijing_now = (
                datetime.datetime.utcnow()
                + datetime.timedelta(hours=8)
            )
            today = beijing_now.date()
        else:
            today = datetime.date.today()

        # False 预约当天，True 预约明天
        delta_day = 1 if self.reserve_next_day else 0

        day = today + datetime.timedelta(
            days=delta_day
        )
        parm = {
            "roomId": roomid,
            "startTime": times[0],
            "endTime": times[1],
            "day": str(day),
            "seatNum": seatid,
            "captcha": captcha,
            "token": token,
            "type": "1",
            "verifyData": "1",
        }
        logging.info(f"submit parameter {parm} ")
        # parm["enc"] = enc(parm)
        parm["enc"] = verify_param(parm, value)
        html = self.requests.post(url=url, params=parm, verify=True).content.decode(
            "utf-8"
        )
        self.submit_msg.append(
            times[0] + "~" + times[1] + ":  " + str(json.loads(html))
        )
        logging.info(json.loads(html))
        return json.loads(html)["success"]
