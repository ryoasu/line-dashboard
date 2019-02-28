# -*- coding: utf-8 -*-
import sys
import re
from datetime import datetime
import pandas as pd
import pathlib
from urllib.request import urlopen
import plotly
import plotly.graph_objs as go
from janome.tokenizer import Tokenizer
from janome.analyzer import Analyzer
from janome.tokenfilter import (
    POSKeepFilter,
    TokenCountFilter,
    CompoundNounFilter,
    LowerCaseFilter,
)

# デリミタ
DELIMITER = '\t'
# 不要な改行のパターン
UNNECESSARY_NEWLINE_PATTERN = re.compile(
    '\n(?!(\d{4}/\d{2}/\d{2}\([日月火水木金土]\)|\d{2}:\d{2}))')
# 日付のパターン
DATE_PATTERN = re.compile('^\d{4}/\d{2}/\d{2}\([日月火水木金土]\)')
# 時間のパターン
TIME_PATTERN = re.compile('^\d{2}:\d{2}')
# スタンプのパターン
STAMP_PATTERN = re.compile('^\[スタンプ\]$')
# 写真のパターン
PICTURE_PATTERN = re.compile('^\[写真\]$')
# アルバムのパターン
ALBUM_PATTERN = re.compile('^\[アルバム\].*')
# ノートのパターン
NOTE_PATTERN = re.compile('^\[ノート\].*')
# 送金のパターン
REMITTANCE_PATTERN = re.compile('\n(.+)[がに][\d,]*(\d) 円[をの]送金(を依頼)*しました。')
# ストップワードのデフォルト(url)
STOP_WORD_URL = ('http://svn.sourceforge.jp/svnroot/slothlib/CSharp/Version1/'
                 'SlothLib/NLP/Filter/StopWord/word/Japanese.txt')


def formated_talks(file_path):
    with open(file_path, encoding="utf-8") as f:
        # 送金メッセージを削除したトーク履歴を取得
        talks = re.sub(REMITTANCE_PATTERN, '', f.read())
        # 不要な改行の削除
        completed_messages = re.sub(UNNECESSARY_NEWLINE_PATTERN, '', talks)

    # タブ文字をカンマに置換してから、末尾の空白文字とダブルクォーテーションを削除し配列化
    formated_talks = [
        line.replace('\"', "").rstrip()
        for line in completed_messages.splitlines()
    ]
    # 最初の一行は不要(タイトル・保存日)なので、それより後ろの要素のみを返す
    return formated_talks[1:]


# TODO: pythonだと末尾再帰最適化がないので、completed_talksをループに変更
# 暫定対応として最大再帰深度を大きな値に設定
sys.setrecursionlimit(50000)


def completed_talks(talks, idx=0, dt_arr=[], comp_talks=[]):
    # talks[idx]がタイムスタンプだった場合
    if re.match(DATE_PATTERN, talks[idx]) is not None:
        # `(曜日)`が不要なので削除
        dt_str = re.sub(r'\(\S\)', '', talks[idx])
        dt = datetime.strptime(dt_str, '%Y/%m/%d')
        dt_arr = [dt.year, dt.month, dt.day]
        return completed_talks(
            talks,
            idx=idx+1,
            dt_arr=dt_arr,
            comp_talks=comp_talks
        )

    # talks[idx]がタイムスタンプ以外(メッセージ)で、最後の要素ではない場合
    elif re.match(DATE_PATTERN, talks[idx]) is None and idx < len(talks)-1:
        message_arr = talks[idx].split(DELIMITER)
        message_type = get_message_type(message_arr[-1])
        message_arr.append(message_type)
        comp_talks.append(dt_arr + message_arr)
        return completed_talks(
            talks,
            idx=idx+1,
            dt_arr=dt_arr,
            comp_talks=comp_talks
        )

    else:
        # 最後の要素がタイムスタンプ以外(メッセージ)の場合
        if re.match(DATE_PATTERN, talks[idx]) is None:
            message_arr = talks[idx].split(DELIMITER)
            message_type = get_message_type(message_arr[-1])
            message_arr.append(message_type)
            comp_talks.append(dt_arr + message_arr)
            return comp_talks
        # 最後の要素がタイムスタンプだった場合は現時点でのcomp_talksを返す
        else:
            return comp_talks


def get_message_type(message_str):
    if re.match(STAMP_PATTERN, message_str) is not None:
        return 'stamp'
    elif re.match(PICTURE_PATTERN, message_str) is not None:
        return 'picture'
    elif re.match(ALBUM_PATTERN, message_str) is not None:
        return 'album'
    elif re.match(NOTE_PATTERN, message_str) is not None:
        return 'note'
    else:
        return 'message'


def get_df_talk(arr):
    # 空のデータフレームを作成
    return pd.DataFrame(
        arr,
        columns=['year', 'month', 'day', 'time', 'user', 'message', 'type'],
    )


def word_count_dict(df, pos=['名詞', '形容詞'], stop_words={}, ):
    # stop_wordsが指定されたいない場合はデフォルト(Slothlib)を使う
    if stop_words == {}:
        f = urlopen(STOP_WORD_URL)
        stop_words = set(f.read().decode("utf-8").split('\r\n'))

    df_message = df_talks[df_talks['type'] == 'message']['message']
    messages = '\n'.join(list(df_message))
    tokenizer = Tokenizer()
    token_filters = [
        CompoundNounFilter(),
        POSKeepFilter(pos),
        LowerCaseFilter(),
        TokenCountFilter(sorted=True)
    ]
    analyzer = Analyzer(tokenizer=tokenizer, token_filters=token_filters)
    # 記号や数字は削除
    pos_res = analyzer.analyze(re.sub(r'[\d!-/:-@[-`{-~]', '', messages))
    return {k: v for k, v in pos_res if k not in stop_words}


def total_messages_per_month(df):
    users = df_talks['user'].unique()
    _df = df.groupby(['year', 'month', 'user'], as_index=False).count()
    _df['year-month'] = _df['year'].astype(str) + \
        '/' + _df['month'].astype(str)

    data = [go.Bar(x=_df[_df['user'] == user]['year-month'],
                   y=_df[_df['user'] == user]['message'],
                   name=user)
            for user in users]
    layout = go.Layout(barmode='stack')
    return {'data': data, 'layout': layout}


def ratio_of_message_type(df):
    _dict = df['type'].value_counts().to_dict()
    return [go.Pie(labels=list(_dict.keys()), values=list(_dict.values()))]


def word_ranking(dict, limit=None):
    limit = len(dict) if limit is None else limit
    words = list(dict.keys())[:limit]
    counts = list(dict.values())[:limit]
    data = [go.Bar(x=words, y=counts, name='counts')]
    return data


if __name__ == '__main__':
    # コマンド引数
    file_path = pathlib.Path(sys.argv[1])
    ranking_limit = sys.argv[2]

    # トーク履歴からデータを取得 (不要な要素の削除・整形)
    talks = formated_talks(file_path)
    # トーク履歴を二次元配列に加工
    comp_talks = completed_talks(talks)
    # トーク履歴の二次元配列をpandas.DataFrameに変換
    df_talks = get_df_talk(comp_talks)
    # メッセージを形態素解析して単語とその総数を算出
    words_with_count = word_count_dict(df_talks)

    plotly.offline.plot(total_messages_per_month(df_talks))
    plotly.offline.plot(ratio_of_message_type(df_talks))
    plotly.offline.plot(word_ranking(words_with_count, ranking_limit))
