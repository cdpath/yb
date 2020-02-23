import argparse
import json
import time
import random
from pathlib import Path
import hashlib
from functools import wraps

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,zh-TW;q=0.8,en;q=0.7,es;q=0.6",
}


#### Utils


def update_cookies():
    global HEADERS
    cookies_cache = "./cookies.txt"
    if not Path(cookies_cache).exists():
        cookies = input("Paste cookies here: ")
        with open(cookies_cache, "w") as f:
            f.write(cookies)
        print("Set cookies to %s" % cookies)
    else:
        with open(cookies_cache) as f:
            cookies = f.read().strip()
        print("Read cookies: %s" % cookies)
    HEADERS["Cookie"] = cookies


def retry(func, n_times=3, wait=3):
    for i in range(n_times - 1):
        try:
            return func()
        except Exception:
            if wait > 0:
                time.sleep(wait)
    return func()


def md5sum(content):
    md5 = hashlib.md5(content)
    return md5.hexdigest()


def download_image(url, output_dir):
    resp = requests.get(url, timeout=5, verify=False)
    if not resp.ok:
        resp.raise_for_status()
    content = resp.content
    md5_ = md5sum(content)
    filename = "%s.%s" % (md5_, url.split(".")[-1])
    with open(output_dir / filename, "wb") as f:
        f.write(content)
    return filename


def cache_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        cache_file = "%s.json" % args[0].book_name
        if Path(cache_file).exists():
            print("Found cache at %s!" % cache_file)
            with open(cache_file) as f:
                result = json.load(f)
        else:
            result = func(*args, **kwargs)
            with open(cache_file, "w") as f:
                json.dump(result, f)
            print("Saved cache to %s!" % cache_file)
        return result

    return wrapper


def make_safe_filename(filename):
    return "".join(
        [c for c in filename if c.isalpha() or c.isdigit() or c == " "]
    ).rstrip()


#### Download


class Book:
    def __init__(self, id_):
        book_info = self.get_book_info(id_)
        self.project_id = book_info["projectId"]
        self.book_name = book_info["name"]

        self.folder_ids = self.parse_folder_ids()

        self.output_dir = Path("./") / self.book_name
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def parse_folder_ids(self):
        resp = self.get_folder_ids()
        for i in resp["data"]:
            yield from self.parse_folder_tree(i)

    @cache_call
    def get_folder_ids(self):
        url = "https://pubcloud.ptpress.cn/pubcloud/content/front/ebookFolderTree"
        params = {"projectId": self.project_id}
        resp = requests.get(url, params=params, headers=HEADERS)
        if resp.ok:
            return resp.json()
        else:
            resp.raise_for_status()

    @staticmethod
    def get_book_info(id_):
        url = "https://pubcloud.ptpress.cn/pubcloud/content/front/portal/getUbookDetail"
        params = {"code": id_}
        resp = requests.get(url, params=params, headers=HEADERS)
        if resp.ok:
            return resp.json()["data"]
        else:
            resp.raise_for_status()

    def get_contents(self, folder_id):
        url = "https://pubcloud.ptpress.cn/pubcloud/content/front/getContentsByFolderId"
        params = dict(folderId=folder_id, projectId=self.project_id)
        time.sleep(random.randint(2, 8))
        resp = requests.get(url, params=params, headers=HEADERS)
        if resp.ok:
            contents = resp.json()["data"]["contents"]
            for line in contents:
                content, editing_content = (
                    line["content"],
                    line["editingContent"],
                )
                if not content and editing_content:
                    content = f'<div class="img"><img src="https://cdn.ptpress.cn/{editing_content}"></div>'
                if content and "img src" in content:
                    print("downloading image...")
                    self.convert_to_local_img(content, self.output_dir)
                yield content
        else:
            resp.raise_for_status()

    def parse_folder_tree(self, tree):
        yield tree
        children = tree.get("children")
        if children:
            for child in children:
                yield from self.parse_folder_tree(child)

    def dump_html(self, folder_info):
        folder_id = folder_info["id"]
        name = folder_info["name"].replace("/", "")
        prefix = str(folder_info["levelCode"]).ljust(12, "0")
        print("%s..." % name)

        contents = self.get_contents(folder_id)
        with open(self.output_dir / f"{prefix}_{name}.html", "w") as f:
            f.writelines(contents)

    @staticmethod
    def convert_to_local_img(markup, image_dir):
        soup = BeautifulSoup(markup, "html.parser")
        imgs = soup.find_all("img")
        for img in imgs:
            try:
                md5_ = retry(lambda: download_image(img["src"], image_dir))
            except Exception as e:
                print("Could not download %s: %s" % (img["src"], e))
            else:
                img["src"] = "../Images/%s" % md5_
        return soup

    def save(self):
        for folder_id in self.folder_ids:
            self.dump_html(folder_id)


def cli():
    parser = argparse.ArgumentParser(description="download online book")
    parser.add_argument("book_id", help="just the `id` in the URL")
    args = vars(parser.parse_args())

    if not args["book_id"]:
        parser.print_help()
        return

    update_cookies()

    book = Book(args["book_id"])
    book.save()


if __name__ == "__main__":
    cli()
