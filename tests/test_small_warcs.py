#!/usr/bin/env python

import os
import commands
from pipes import quote

warcs = {'alexa_short_header.arc.gz':      'net,killerjo)/robots.txt 20110804181142 http://www.killerjo.net:80/robots.txt unk - YZI2NMZ5ILYICUL3PNYVYQR3KI2YY5EH - - 139 161 alexa_short_header.arc.gz',
         'bad_mime_type.arc.gz':           'net,naver,cafethumb)/20101223_84/qkrgns3_129303386816936xuq_jpg/imag0030_qkrgns3.jpg 20120407152447 http://cafethumb.naver.net/20101223_84/qkrgns3_129303386816936xUq_jpg/imag0030_qkrgns3.jpg unk 200 OUK52MTLKPEA6STHTFFPFI2JP7G4QBUZ - - 3587 153 bad_mime_type.arc.gz',
         'crlf_at_1k_boundary.warc.gz':    'nz,co,tradeaboat,whitiangamarine)/emailafriend.aspx?item=h4siagw4x00a/wfwao/9gaxg6utmkolwv1zy9nohybsaoj36okttm/cdglv9et4wgw8ywbkoacccfsjvdmf7bge+ke8edgs5h4ib0rue96yj2/r5lixmy1sueue5iihmyms9jl9femizgo6yaew0fx+snckd5d+ow5216i0sj9yb0pzj/i/3z3mannav042wjyfyugogpn6yv2wzgueerk5fqi+msasd88rtsytzkszuc/mtpdowhevxiy3n2+r1n6q9utfvekuy5bonzpqy7blk93yj9dnviit0zjmshgotxc0nuywionfpixfogmm8y6i3rfxxqxd5p95qmiogdi1rvpgkcav+go4nz4r/caicl697pcwfkcqyfw5zts74+snrdessbdz2quceotydcw2gh3hogkrrupiqn9hfdvsb2p3hxp/ygkh9w6+d8jp7tylmalvnjjevst/6wlbqrhwrsnlpxntjxqzrtw7z8e/+o5bfsb6hgwfxzulqz2rnnfvazomgkckthoprtba6cp5ifb8j8sfov7pvwifngclbr28ekmjaebqrznblb4njweisomyenibp/qlvpv4sqarzduhs1qri9toq/toiasrlkpq+sdsbuzqjxij9b/tjgx8biqe129tdob0bdhtexwqq1aoaasxmtqddrykqcrvckjfh1ayszhyl9p6xs6lwmalo2mygxnzegkrvpfr5c/edjp6hr/28egr4fdxyyrwaumhoprqgxyjtq7nqwv7m8jyyvxcfgpx6kz6ftu4nmbahpuhgxd/eddp5y3duicjbcaymmvvmojqxmxb8cpsytv9zcu1rn5ehrp2iypudy+6ihhacaaa= 20110218233256 http://whitiangamarine.tradeaboat.co.nz/emailAFriend.aspx?item=H4sIAGW4X00A%2fwFwAo%2f9gaXg6UTMkoLWV1Zy9nOhybsaOj36okTTM%2fCdGlV9et4wGW8ywbKoacCcFSjvDmf7BgE%2bke8eDGs5H4ib0RuE96Yj2%2fR5LIXmy1SUEue5IiHmYmS9jl9femiZGo6yAeW0fX%2bSnCkd5D%2bOW5216i0SJ9yb0PZJ%2fI%2f3z3manNAv042wJYFyUgOGpN6yV2wZGUEERk5FQI%2bmSASd88RTsytzksZuC%2fmTpDowhevXiY3N2%2br1n6Q9utfvEKuy5bonZPqy7BlK93yJ9DnviiT0ZJMsHGOTXC0NUywIonFpIXfogmm8y6I3RfXxQXD5p95qmiogdI1rvPgKCaV%2bgO4nZ4r%2fCAicl697pcwFKCQyFW5ZTS74%2bSnrdEssBdz2quceotYDcW2GH3hogkrRupiqN9hFdVsb2p3HXP%2fYGkH9W6%2bD8jp7TyLmALvnJJevST%2f6wlbQRhWrsNlPXnTjxQZrTw7z8E%2f%2bo5BFsb6HgWfXzULQZ2RnNFvAZOMgkcKtHopRTbA6cp5ifB8j8sFoV7PVwifNgcLBR28EKMjAeBqRZnBlB4nJwEISomyeNIBP%2fQlvpV4sqArZdUhs1qRi9TOQ%2fToiaSrlKpq%2bSdSbuZqjXIJ9b%2ftjgx8biQe129TDOB0BDHtEXwqq1aoaASxmTqddrYKqCRvcKjfH1aYSZHyL9p6xS6LwMAlO2myGxnZeGkrVpfr5C%2fEDJp6HR%2f28EgR4fdXyyRWauMhoPrQgXYJTq7NQwv7m8JYyvxCfGpX6Kz6ftu4NMBAHPuhGxd%2fEDDP5y3DUIcJBCAyMMvvMOJQXMXb8cpsyTv9ZcU1RN5ehrp2iyPudY%2b6iHHACAAA%3d text/html 200 M4VJCCJQJKPACSSSBHURM572HSDQHO2P - - 2588 0 crlf_at_1k_boundary.warc.gz',
         'crlf_at_1k_boundary_2.warc.gz':  'au,com,grandtourer)/aspx/login.aspx?4=h6vklmshqnbpvsscb7x7iu2/luokwckr5nsukefi3ygag1wtqor9vtiwv+anh9su4shtqmrrjy53dhqpxif+vjqkb+tajvfhn/sn1oqgaxly4i1ciwbi6jbk+i0fqqn44wt18szrgn95ygnruk9baymdquzchh7i/pak180zcfccrud+lqmmukvlvg0qoq6kvbos8dqo3mh5unwoclxiid2+mbma2rfp/015+o5+dnrq/umof3aettvsy7i/bcmgkbn/6wqknr04kfi4ppwjig2vcw4av8hj2fqbo+3jutdryfgyulizuqjebrh0lmah9sgkrpomwa0hgzmvf1ahoyqbvnbwujeekckxrydnd+dtxyozqlpygn/gcedbkoubmmmldsl+stl4qzomxngk3xnxiw+/csq/pwyimcbtdl/fxvnj6j4l3m5v66mjhxmyzk/wfp7spfzeghl+x4ih9dzzl8nqr/+ma7e6jhmyx4/dwkresqh3mzmiqddmdp6cjtnxapulfamv/tdy1vgjdl4pbiasartibf4nnxlglpvcy+cm3j83nybyytxbrx9+x1vcvnvpo8sipspuyp8xi0glnsmaw/u+owll28euzdlvanmz2j0rcdhtqkyejfhn/rm4z1gkhwn2rexkykbgtnuppthr08v6sur9kagw9dzdyut0go9fjshgpbmnm0uaujtzkshhi0uriz2cnn+arsppeayooy3yedrv7vklewh6mj3yjqfzwj4tbq75wecrm9gw4p+7uwal4wc92gjdip7g1p2cm4vbtvahp1ntq+shd4oot5r6hza2igo85st3ftgfvfj7eolin+dixrjdwa== 20120422095915 https://www.grandtourer.com.au/Aspx/Login.aspx?4=H6VKLMsHqnBpvsscB7x7Iu2%2fLUOKwCKr5nsukefI3ygAG1WTqOR9vtiWv%2banh9sU4sHTQmRRJY53DHQpXiF%2bVjqKB%2btaJvfHn%2fSN1OQgaxlY4i1Ciwbi6jbK%2bI0fQqn44Wt18szRgN95ygNRUK9BaYMdqUzChH7I%2fpAk180zCFCCRUD%2bLqMMuKvLVg0qOQ6Kvbos8DqO3MH5UnwOcLxiID2%2bmBMA2Rfp%2f015%2bo5%2bDNRq%2fUMOF3aETtvSY7i%2fbCmGKBn%2f6WqkNr04Kfi4PPWJIg2VCw4AV8hj2FqbO%2b3JUtdRYfGYulizuQJEbrh0LMah9sGKRPomWA0hgZmvf1AHoYqbVNbwUJeEKCKxrYdND%2bDtxyOzQlpygN%2fgCeDbKOuBMMMLdSl%2bsTl4qZoMXnGK3XNxiw%2b%2fcsq%2fPWyIMCBtdl%2ffXvnJ6J4L3M5v66mjhXmyZk%2fwfp7SpfzegHL%2bX4iH9DZzl8nqr%2f%2bmA7E6JHmyX4%2fDWKrEsqH3MZMIqddmDp6cJtnxAPULfAmv%2fTDY1VGJdl4PBIASArTIBF4nnXLglpvcy%2bcm3j83nyByyTxbRX9%2bX1VcVNvPo8SIpSpuYP8xi0GlNsMaW%2fu%2bowll28EUzDLVAnMz2j0rcdhTqKYEJfhN%2frm4Z1gKhwn2REXKykBGTnupPtHR08V6Sur9kAgW9DZdyUt0Go9fJshGPBmNm0uAUjtzkshhI0UrIz2cnn%2bArspPeaYOOY3YEdrV7VKlEWh6Mj3yjQFZwj4TbQ75WECrM9Gw4p%2b7uWaL4wc92gjDiP7G1P2cM4vBTVAHP1nTQ%2bShD4OoT5r6hZA2igo85St3ftgfvfJ7eOLin%2bdixRJdwA%3d%3d text/html 200 5STDGW7HDWZQ4TPS4GPBOL3TEG7NQRHE - - 6934 0 crlf_at_1k_boundary_2.warc.gz', #from NLA-AU-CRAWL-006-20120421051259635-00205-02593-crawling119/NLA-AU-CRAWL-006-20120422094450650-02571-3266~web-crawl001.us.archive.org~8443.warc.gz offset 90441596
         'giant_html.warc.gz':             'com,guide-fleurs)/site/partenaires.htm 20120121173511 http://www.guide-fleurs.com/site/partenaires.htm text/html 200 BGA6K3VEQVACI7KVTAGRNMBAPIYIGELF - - 1882583 0 giant_html.warc.gz',
         'negative_content_length.arc.gz': 'com,lastdaywatchers)/robots.txt 20120420180002 http://www.lastdaywatchers.com/robots.txt text/html 301 3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ http://lastdaywatchers.com/robots.txt/ - 244 155 negative_content_length.arc.gz\ncom,diggheadlines)/robots.txt 20120420180002 http://diggheadlines.com/robots.txt unk 502 3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ - - 103 520 negative_content_length.arc.gz'
        }

for file, cdx in warcs.iteritems():

    warc_file = quote(file)
    assert os.path.exists(warc_file)

    print "processing", warc_file

    cmd = '../cdx_writer.py %s' % warc_file
    print "  running", cmd
    status, output = commands.getstatusoutput(cmd)
    assert 0 == status


    assert output.endswith(cdx)

print "exiting without errors!"
