import json
import time
import argparse
import os
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


from utils import reserve, get_user_credentials

get_current_time = lambda action: (
    time.strftime("%H:%M:%S", time.localtime(time.time() + 8 * 3600))
    if action
    else time.strftime("%H:%M:%S", time.localtime(time.time()))
)
get_current_dayofweek = lambda action: (
    time.strftime("%A", time.localtime(time.time() + 8 * 3600))
    if action
    else time.strftime("%A", time.localtime(time.time()))
)

RUN_ONCE = True
SLEEPTIME = 0.5  # 每次抢座的间隔
ENDTIME = "20:02:00"  # 根据学校的预约座位时间+1min即可
RESERVE_TIME = "20:00:00"  # 北京时间
PREWARM_LEAD_SECONDS = 20  # 正式预约前多少秒完成运行环境和网络预热

ENABLE_SLIDER = True  # 是否有滑块验证
MAX_ATTEMPT = 1  # 最大尝试次数
RESERVE_NEXT_DAY = True  # 预约明天而不是今天的
POST_LOGIN_DELAY = 3.0   # 登录成功后等待2秒
RETRY_INTERVAL = 15.0    # 整批失败后等待15秒

def create_reserve_clients(user_count):
    clients = []
    for _ in range(user_count):
        client = reserve(
            sleep_time=SLEEPTIME,
            max_attempt=MAX_ATTEMPT,
            enable_slider=ENABLE_SLIDER,
            reserve_next_day=RESERVE_NEXT_DAY,
        )
        client.warm_up()
        clients.append(client)
    return clients


def login_and_reserve(
    users,
    usernames,
    passwords,
    action,
    success_list=None,
    clients=None,
):
    logging.info(
        f"Global settings: \nSLEEPTIME: {SLEEPTIME}\nENDTIME: {ENDTIME}\nENABLE_SLIDER: {ENABLE_SLIDER}\nRESERVE_NEXT_DAY: {RESERVE_NEXT_DAY}"
    )
    if action and len(usernames.split(",")) != len(users):
        raise Exception("user number should match the number of config")
    if success_list is None:
        success_list = [False] * len(users)
    if clients is None:
        clients = create_reserve_clients(len(users))
    current_dayofweek = get_current_dayofweek(action)
    for index, user in enumerate(users):
        username, password, times, roomid, seatid, daysofweek = user.values()
        if action:
            username, password = (
                usernames.split(",")[index],
                passwords.split(",")[index],
            )
        if current_dayofweek not in daysofweek:
            logging.info("Today not set to reserve")
            continue
        if not success_list[index]:
            logging.info(
                f"----------- {username} -- {times} -- {seatid} try -----------"
            )
            s = clients[index]
            if not s.logged_in:
                s.get_login_status()
                login_success, _ = s.login(username, password)
                if not login_success:
                    continue
                logging.info(
                f"登录后等待 {POST_LOGIN_DELAY} 秒再预约"
                )
                time.sleep(POST_LOGIN_DELAY)
            s.requests.headers.update({"Host": "office.chaoxing.com"})
            suc = s.submit(times, roomid, seatid, action)
            success_list[index] = suc
    return success_list, clients


def main(users, action=False):
    # 1. 第一步：如果是 GitHub Action，先把账号密码从环境变量里拿出来
    # 这一步要在八点前做完，不能等八点到了才现拿
    usernames, passwords = None, None
    clients = None
    if action:
        usernames, passwords = get_user_credentials(action)

        # 2. 第二步：在预约时间前完成预热，避免首个座位承担冷启动耗时
        import datetime
        reserve_clock = datetime.datetime.strptime(
            RESERVE_TIME, "%H:%M:%S"
        ).time()
        logging.info(
            f"GitHub Action 模式已启动，等待北京时间 {RESERVE_TIME}..."
        )
        while True:
            now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
            target = datetime.datetime.combine(now.date(), reserve_clock)
            # Support test times shortly after midnight when the workflow starts
            # on the previous evening. A target more than 12 hours in the past
            # is treated as the next day's target.
            if (now - target).total_seconds() > 12 * 3600:
                target += datetime.timedelta(days=1)
            remaining_seconds = (target - now).total_seconds()

            if clients is None and remaining_seconds <= PREWARM_LEAD_SECONDS:
                logging.info("开始预约前预热...")
                clients = create_reserve_clients(len(users))

            if remaining_seconds <= 0:
                logging.info(f"到达预定时间: {now.strftime('%H:%M:%S')}，开始抢座！")
                break

            time.sleep(1 if remaining_seconds > 10 else 0.05)

    if clients is None:
        clients = create_reserve_clients(len(users))

    # 3. 第三步：原有的抢座逻辑开始执行
    current_time = get_current_time(action)
    logging.info(f"start time {current_time}, action {'on' if action else 'off'}")
    attempt_times = 0
    success_list = None
    current_dayofweek = get_current_dayofweek(action)
    today_reservation_num = sum(
        1 for d in users if current_dayofweek in d.get("daysofweek")
    )
    
    while current_time < ENDTIME:
        attempt_times += 1
        success_list, clients = login_and_reserve(
            users,
            usernames,
            passwords,
            action,
            success_list,
            clients,
        )
        print(
            f"attempt time {attempt_times}, time now {current_time}, success list {success_list}"
        )
        current_time = get_current_time(action)
        if success_list and sum(success_list) == today_reservation_num:
            print("reserved successfully!")
            return

        if RUN_ONCE:
            logging.info(
        "单轮模式结束，不再重新生成验证码"
    )
            return

def debug(users, action=False):
    logging.info(
        f"Global settings: \nSLEEPTIME: {SLEEPTIME}\nENDTIME: {ENDTIME}\nENABLE_SLIDER: {ENABLE_SLIDER}\nRESERVE_NEXT_DAY: {RESERVE_NEXT_DAY}"
    )
    suc = False
    logging.info(f" Debug Mode start! , action {'on' if action else 'off'}")
    if action:
        usernames, passwords = get_user_credentials(action)
    current_dayofweek = get_current_dayofweek(action)
    for index, user in enumerate(users):
        username, password, times, roomid, seatid, daysofweek = user.values()
        if type(seatid) == str:
            seatid = [seatid]
        if action:
            username, password = (
                usernames.split(",")[index],
                passwords.split(",")[index],
            )
        if current_dayofweek not in daysofweek:
            logging.info("Today not set to reserve")
            continue
        logging.info(f"----------- {username} -- {times} -- {seatid} try -----------")
        s = reserve(
            sleep_time=SLEEPTIME,
            max_attempt=MAX_ATTEMPT,
            enable_slider=ENABLE_SLIDER,
            reserve_next_day=RESERVE_NEXT_DAY,
        )
        s.warm_up()
        s.get_login_status()
        s.login(username, password)
        s.requests.headers.update({"Host": "office.chaoxing.com"})
        suc = s.submit(times, roomid, seatid, action)
        if suc:
            return


def get_roomid(args1, args2):
    username = input("请输入用户名：")
    password = input("请输入密码：")
    s = reserve(
        sleep_time=SLEEPTIME,
        max_attempt=MAX_ATTEMPT,
        enable_slider=ENABLE_SLIDER,
        reserve_next_day=RESERVE_NEXT_DAY,
    )
    s.warm_up()
    s.get_login_status()
    s.login(username=username, password=password)
    s.requests.headers.update({"Host": "office.chaoxing.com"})
    encode = input("请输入deptldEnc：")
    s.roomid(encode)


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    parser = argparse.ArgumentParser(prog="Chao Xing seat auto reserve")
    parser.add_argument("-u", "--user", default=config_path, help="user config file")
    parser.add_argument(
        "-m",
        "--method",
        default="reserve",
        choices=["reserve", "debug", "room"],
        help="for debug",
    )
    parser.add_argument(
        "-a",
        "--action",
        action="store_true",
        help="use --action to enable in github action",
    )
    args = parser.parse_args()
    func_dict = {"reserve": main, "debug": debug, "room": get_roomid}
    with open(args.user, "r+") as data:
        usersdata = json.load(data)["reserve"]
    func_dict[args.method](usersdata, args.action)
