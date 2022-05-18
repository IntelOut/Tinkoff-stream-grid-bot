Никто не знает пойдут ли акции вверх или вниз, это всё - [хумера](youtu.be/WKvjOjfyLqk?t=32) (с)<br>
Поэтому я выбрал для себя стратегию:<br>
«Продавай пока дорого, покупай пока дешево»<br>

## Сеточный бот для Тинькофф Инвестиций

Создайте в корне директории файл token.txt<br>
1я строчка - токен<br>
2я строчка - account id<br>
Впишите ваш токен, номер счета. <br>
Заполните тикеры и количество линий в основном файле.<br>

Например, если напишите<br>
"TCS": {"number": 8, "price_step": 3 / 100, "quantity": 1, "start_price": 0}<br>
то торговля будет вестись по бумагам Тинькофф, тикер TCS<br>
будет выставлено 4 ордера на покупку и 4 ордера на продажу,<br>
ордера будут с шагом в 3%,<br>
в ордерах будет по 1 акции,<br>
ордера будут выставляться от текущей цены,<br>
торги будут идти на указанном счете.<br>
Следующей строкой можно задать так же вторую бумагу и последующие<br>
<br>
Оптимально, чтобы у вас были 4 бумаги TCS и деньги еще на 4 акции.<br>
Если этого нет — бот будет пытаться выставить соответствующие ордера,<br>
но вылетать не будет.<br>
Если цена упадет и бот купит одну бумагу TCS,<br>
он выставит ордер на продажу по цене = цена покупки + price_step<br>
Таким образом у вас будет 3 ордера на покупку и 5 ордеров на продажу.<br>
Когда биржа закроется, ордера отменятся.<br>
Когда биржа откроется, бот перевыставит ордера по тем же параметрам.<br>





## Начало работы

<!-- termynal -->

```
$ pip install tinkoff-investments
```

- [Документация от Тинькофф](https://github.com/Tinkoff/invest-python)
<br>

В планах:<br>
<ol><li>Переписать верхние ордера с лимитных на тейк-профит.<br>
У этого решения есть два плюса:<br>
— Можно не перевыставлять ордера на продажу каждый торговый день.<br>
— Можно выставлять их на любую цену, игнорируя ограничения биржи по максмальной цене.<br>
</li>
<li>Сохранять цену последней покупки на следующий день,<br>
Иногда торги открываются с гэпом, и некорректно работает логика выставления skip-price<br>
</li>
<li>После каждой покупки выставлять стоп-лосс от цены покупки,<br>
хотя бы номинальный, на резкое падение, например, на 40%</li>
<li>
Передавать боту расписание работы биржи, чтоб не спамил круглосуточно
</li>
<li>
Корректировать Шаг цены и количество акций в ордере в зависимости от волатильности бумаги
</li>
<li>  
Выставлять ордера не точно по сетке,<br>
а в местах наименьшего сопротивления.<br>
  Например, по сетке buy ордер должен был выставиться на 199.9₽.<br>
  Но уровень 200 — сильный, под ним много ордеров на покупку.<br>
  Если выставить 200.1₽, то большая вероятность что ордер исполнится<br>
  и если уровень 200₽ выстоит цена отскочит.<br>
  А если так и будет стоять ордер 199.9₽,<br>
  то скорей всего до него не добьёт<br>
  а если добьёт, то скорей всего цена полетит вниз.
</li>
</ol>
