//%attributes = {}
C_TEXT:C284($1)

C_OBJECT:C1216($json)

$json:=JSON Parse:C1218($1;Is object:K8:27)

Case of 
	: ($json.type=Volume did mount event)
		
	: ($json.type=Volume did rename event)
		
	: ($json.type=Volume did unmount event)
		
	: ($json.type=Volume will unmount event)
		
End case 