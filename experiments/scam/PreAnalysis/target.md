# 従来研究で示されたパターン

## 従来研究：thesis/SCAM2026_NoguchiH_ja/bib/Performance Issues and Optimizations  in JavaScript-  An Empirical Study.pdf

## ID1 
### description

Prefer Object.keys() over computing the properties of an object with a for-in loop.

### Example
- before

```
for ( var key in obj ) {
    if ( obj.hasOwnProperty( key ) )
    { ... }
}
```

- after  

```
var keys = Object.keys( obj ) ;
for ( var i =0, l = keys.length; i < l ; i ++) {
    var key = keys[i];
}
```

## ID2
### description

To extract a substring of length one, access the character directly instead of calling substr().

### Example
- before

```
str.substr(i,1);
```

- after  

```
str[i]
```

## ID3
### description

To convert a value into a string, use implicit type conversion instead of String().

### Example
- before

```
starts = String(starts); 
```

- after  

```
starts = '' + starts;
```

## ID4
### description

Use jQuery’s empty() instead of html(’’).

### Example
- before

```
body.html('');
```

- after  

```
body.empty();
```

## ID5
### description

Use two calls of charAt() instead of substr().

### Example
- before

```
key.substr(0,2) !== '$$'
```

- after  

```
key.charAt(0) !== '$' && key.charAt (1) !== '$' 
```

## ID6
### description

To replace parts of a string with another string, use replace() instead of split() and join().

### Example
- before

```
str.split ("'").join("\\'")
```

- after  

```
str.replace(/ '/g , "\\'" ) 
```

## ID7
### description

Instead of checking an object’s type with toString(), prefer the instanceof operator.

### Example
- before

```
if ( toString.call ( err ) === "[ object Error ]") ...
```

- after  

```
if ( err instanceof Error || toString.call( err ) === "[ object Error ]") ...
```

## ID8
### description

For even/odd checks of a number use &1 instead of %2

### Example
- before

```
index % 2 == 0 
```

- after  

```
index & 1 == 0 
```

## ID9
### description

Prefer for loops over functional style processing of arrays.

### Example
- before

```
styles.reduce (
    function (str, name) {
        return ... ;
}, str ) ;
```

- after  

```
for (var i =0; i < styles.length; i ++) {
    var name = styles [ i ];
    str = ... ; }           
return str ;
```

## ID10
### description

When joining an array of strings, handle single-element arrays eﬃciently.

### Example
- before

```
[].slice.call( arguments ).join ('') 
```

- after  

```
arguments.length === 1 ?
    arguments [0] + ’ ’ :
    [].slice.call ( arguments ).join( ’ ’) ;
```