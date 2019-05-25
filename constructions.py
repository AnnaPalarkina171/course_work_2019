import nltk
from rusenttokenize import ru_sent_tokenize
from collections import OrderedDict
import os
import re
import copy
import json
import codecs
import shutil
import treetaggerwrapper
import sqlite3
import rusclasp
from conllu import parse
tagger = treetaggerwrapper.TreeTagger(TAGLANG='ru')

input_text = 'Параллельно с этим были ужесточены правила проведения массовых мероприятий: в частности, митингующим запретили ставить палатки.'

#разделяем на предложения и анализируем их отдельно
def input():
    sents = ru_sent_tokenize(input_text)
    for result in sents:
        #смотрим, как разделяет rusclasp
        clauses_num = []
        begins = []
        ends = []
        split_punc = []
        rusclasp_clauses = []
        s = rusclasp.Splitter()
        result = s.split(input_text)
        entities = result['entities']
        for section in entities:
            sec_num = section[2]
            clauses_num.append(sec_num)
            begins.append(sec_num[0][0])
            ends.append(sec_num[0][1])
            split_punc.append(sec_num[0][1] + 1)
            for x in sec_num:
                clause = input_text[x[0]:x[1]]
                rusclasp_clauses.append(clause)

        #проверяем, не выделил ли отдельно вводные конструкции
        with open('constructions.txt', 'r', encoding='utf-8') as f:
            constructions = f.read()
            for const in constructions.split('\n'):
                for rus_clause in rusclasp_clauses:
                    if rus_clause != const:
                        pass
                        #тут нужно просто вывести ЭДЕ, так как в предложении нет вводных конструкций
                    else:
                        i=0
                        for rus_cl in rusclasp_clauses:
                            if rus_cl == const:
                                split_punc = split_punc
                                table(split_punc)
                                clause_section = clauses_num[i]
                                linking_words(clause_section, split_punc)
                            else:
                                i+=1




#используем эту функцию если какие-то предикации не совпадают с ЭДЕ, чтобы построить синтаксическое дерево и посмотреть, что от чего зависит
def table(split_punc):
    conn = sqlite3.connect('constructions.db')
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS tokens(id, form, lemma, upostag, feats, head, deprel, begin, end, rcl_split)")
    new_analysis = []
    result = input_text
    result = re.sub(u'["«»‘’]', u'\'', result, flags=re.U)
    result = re.sub(u'(^|\. )\'(.+?)\'(, ?)([—-])', u'\\1"\\2"\\3~', result, flags=re.U)
    analysis = tagger.tag_text(result, tagblanks=True)
    position = 0
    for token in analysis:
        if token[0] == '<':
            position += 1
        else:
            new_token = dict(begin=position)
            new_token['text'] = token.split(u'\t')[0]
            position += len(new_token['text'])
            new_token['end'] = position
            new_analysis.append(new_token)

    with open('constructions.conllu', 'r', encoding='utf-8') as f: #тут должна быть библиотека, а не просто открытие файла conllu, но пока с ней проблемы, поэтому так
        text = f.read()
        sentences = parse(text)
        sentence = sentences[0]
        id = [inf['id'] for inf in sentence]
        form = [inf['form'] for inf in sentence]
        lemma = [inf['lemma'] for inf in sentence]
        upostag = [inf['upostag'] for inf in sentence]
        feats = [inf['feats'] for inf in sentence]
        head = [inf['head'] for inf in sentence]
        deprel = [inf['deprel'] for inf in sentence]
        begin = [word['begin'] for word in new_analysis]
        end = [word['end'] for word in new_analysis]
        for i in range(len(id)):
            feat = feats[i]
            if feat == None:
                feat_i = 'None'
            else:
                feat_i = ','.join(list(feats[i].values()))
            if end[i] in split_punc:
                rcl_split = 1
            else:
                rcl_split = 0
            c.execute("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?)", (id[i], form[i], lemma[i], upostag[i], feat_i, head[i], deprel[i], begin[i], end[i], rcl_split))

    conn.commit()


#Эта для вводных слов
def linking_words(clause_section, split_punc):
    delete_parse = []
    conn = sqlite3.connect('constructions.db')
    c = conn.cursor()
    for x in clause_section:
        first_punc = x[0]
        last_punc = x[1]
        for row in c.execute('SELECT * FROM tokens ORDER BY id'):
            if row[8] == first_punc - 1:
                f_p_id = row[0]
            if row[8] == last_punc + 1:
                l_p_id = row[0]
        for x in range(f_p_id + 1, l_p_id):
            for row in c.execute('SELECT * FROM tokens ORDER BY id'):
                if row[0] == x:
                    if row[5] >= l_p_id:
                        sec_punc = f_p_id
                        delete_parse.append(last_punc + 1)
                        #зависит от правой клаузы
                    if row[5] <= f_p_id:
                        sec_punc = l_p_id
                        delete_parse.append(first_punc - 1)
                        #зависит от левой клаузы


        #теперь решаем, что делать со второй границей вводной конструкции - склеивать или нет

        #если ВК зависит от правой клаузы, смотрим от чего зависит левая
        if sec_punc == f_p_id:
            for row in c.execute('SELECT * FROM tokens ORDER BY id'):
                for i in range(1, sec_punc):
                    if row[0]  == i:
                        if row[5] > l_p_id:
                            if f_p_id not in delete_parse:
                                delete_parse.append(first_punc - 1)
                        else:
                            pass

        # если ВК зависит от левой клаузы, смотрим от чего зависит правая
        if sec_punc == l_p_id:
            for row in c.execute('SELECT * FROM tokens ORDER BY id'):
                for i in range(l_p_id):
                    if row[0]  == i:
                        if row[5] < f_p_id:
                            if l_p_id not in delete_parse:
                                delete_parse.append(last_punc + 1)
                        else:
                            pass

    #Выставляем новые границы
    new_parse = []
    for x in split_punc:
        if x not in delete_parse:
            if x != len(input_text):
                new_parse.append(x)

    #Выдаём правильные склеивания
    clauses = []
    i = 0
    l = len(new_parse)
    if new_parse != []:
        for i in range(l + 1):
            if i == 0:
                clauses.append(input_text[i:new_parse[i]])
            if i > 0:
                if i == l:
                    clauses.append(input_text[new_parse[i - 1]:])
                else:
                    clauses.append(input_text[new_parse[i - 1]:new_parse[i]])
        for x in clauses:
            print(x)
    else:
        print(input_text)



input()