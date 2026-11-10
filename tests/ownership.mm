#include "4DPlugin-Mount.cpp"
#include "4DPlugin-JSON.h"
#include "ARRAY_TEXT.h"
#include "PrivateTypes.h"
#include "EntryPoints.h"
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <map>
#include <set>

namespace {
std::map<PA_Unichar *, size_t> strings;
std::map<PA_Handle, size_t> handles;
struct Reference { int count; };
std::set<Reference *> references;
bool allocatedEmpty = true;
bool directMethod = true;
bool propertyPresent = true;
PA_Variable property = {};
PA_Variable stored = {};
PA_VariableKind returnKind = eVK_Undefined;
CUTF16String expected;
unsigned calls = 0;
const PA_Unichar empty[] = {0};

PA_Unistring makeString(const PA_Unichar *text)
{
    size_t length = 0;
    if(text) while(text[length]) ++length;
    PA_Unistring result = {};
    result.fLength = length;
    if(length || allocatedEmpty)
    {
        result.fString = new PA_Unichar[length + 1];
        if(length) memcpy(result.fString, text, length * sizeof(PA_Unichar));
        result.fString[length] = 0;
        PA_Unichar *buffer = result.fString;
        strings[buffer] = length;
    }
    return result;
}

void checkString(PA_Unistring value, const CUTF16String &text)
{
    assert(value.fLength == text.size());
    if(value.fString)
    {
        PA_Unichar *buffer = value.fString;
        assert(strings.count(buffer));
        assert(strings.at(buffer) == text.size());
        assert(CUTF16String(value.fString, value.fLength) == text);
        assert(value.fString[value.fLength] == 0);
    }else{
        assert(text.empty());
    }
}

void freeString(PA_Unistring value)
{
    if(!value.fString) { assert(value.fLength == 0); return; }
    PA_Unichar *buffer = value.fString;
    assert(strings.erase(buffer) == 1);
    delete[] value.fString;
}

Reference *newReference()
{
    Reference *ref = new Reference{1};
    references.insert(ref);
    return ref;
}

void release(void *pointer)
{
    if(!pointer) return;
    Reference *ref = static_cast<Reference *>(pointer);
    assert(references.count(ref));
    if(--ref->count == 0)
    {
        references.erase(ref);
        delete ref;
    }
}

PA_Variable copyVariable(PA_Variable value)
{
    if(value.fType == eVK_Unistring)
    {
        checkString(value.uValue.fString,
                    CUTF16String(value.uValue.fString.fString ?
                                 value.uValue.fString.fString : empty,
                                 value.uValue.fString.fLength));
        value.uValue.fString = makeString(value.uValue.fString.fString);
    }else if(value.fType == eVK_Object || value.fType == eVK_Collection){
        Reference *ref = static_cast<Reference *>(value.uValue.fObject);
        if(ref) { assert(references.count(ref)); ++ref->count; }
    }
    return value;
}

void clear(PA_Variable *value)
{
    if(value->fType == eVK_Unistring) freeString(value->uValue.fString);
    else if(value->fType == eVK_Object || value->fType == eVK_Collection)
        release(value->uValue.fObject);
    else if(value->fType == eVK_ArrayUnicode)
    {
        auto h = value->uValue.fArray.fData;
        if(h)
        {
            for(int i = 0; i <= value->uValue.fArray.fNbElements; ++i)
                freeString(reinterpret_cast<PA_Unistring *>(*h)[i]);
            assert(handles.erase(h) == 1);
            free(*h);
            delete h;
        }
    }
    *value = {};
}

PA_Variable resultVariable()
{
    PA_Variable result = {};
    result.fType = returnKind;
    if(returnKind == eVK_Unistring)
        result.uValue.fString = makeString(expected.c_str());
    else if(returnKind == eVK_Object || returnKind == eVK_Collection)
        result.uValue.fObject = newReference();
    return result;
}

// Only the engine boundary is simulated; all PA_* operations use the full SDK.
void engine(short selector, EngineBlock *eb)
{
    eb->fError = eER_NoErr;
    switch(selector)
    {
        case EX_CREATE_UNISTRING:
            eb->fUniString1 = makeString(reinterpret_cast<PA_Unichar *>(eb->fHandle));
            break;
        case EX_DISPOSE_UNISTRING:
            freeString(eb->fUniString1);
            break;
        case EX_SET_UNISTRING:
        {
            PA_Unistring replacement = makeString(reinterpret_cast<PA_Unichar *>(eb->fHandle));
            freeString(eb->fUniString1);
            eb->fUniString1 = replacement;
            break;
        }
        case EX_CLEAR_VARIABLE:
            clear(static_cast<PA_Variable *>(eb->fPtr1));
            break;
        case EX_VARIABLE_TO_STRING:
        {
            auto value = reinterpret_cast<PA_Variable *>(eb->fHandle);
            assert(value->fType == eVK_Unistring);
            eb->fUniString1 = value->uValue.fString;
            break;
        }
        case EX_HANDLE_MANAGER:
        {
            PA_Handle h = eb->fHandle;
            switch(eb->fParam1)
            {
                case 1:
                    h = new char *;
                    *h = static_cast<char *>(calloc(1, eb->fParam2 ? eb->fParam2 : 1));
                    handles[h] = eb->fParam2;
                    eb->fHandle = h;
                    break;
                case 2:
                    assert(handles.erase(h) == 1);
                    free(*h);
                    delete h;
                    break;
                case 3:
                    assert(handles.count(h));
                    *h = static_cast<char *>(realloc(*h, eb->fParam2 ? eb->fParam2 : 1));
                    handles[h] = eb->fParam2;
                    break;
                case 4:
                    eb->fParam2 = handles.at(h);
                    break;
                case 5:
                    assert(handles.count(h));
                    eb->fParam3 = reinterpret_cast<sLONG_PTR>(*h);
                    break;
                case 6:
                    assert(handles.count(h));
                    break;
                default: assert(false);
            }
            break;
        }
        case EX_GET_METHOD_ID:
            eb->fParam1 = directMethod ? 42 : 0;
            break;
        case EX_CALL_BY_PROCID:
        {
            assert(eb->fParam1 == 42 && eb->fParam2 == 1);
            PA_Variable *vars = reinterpret_cast<PA_Variable *>(*eb->fHandle);
            checkString(vars[1].uValue.fString, expected);
            vars[0] = resultVariable();
            if(returnKind == eVK_Unistring && !expected.empty())
                assert(vars[0].uValue.fString.fString != vars[1].uValue.fString.fString);
            ++calls;
            break;
        }
        case EX_EXECUTE_COMMAND_BY_ID:
        {
            auto args = static_cast<PA_Variable **>(eb->fPtr1);
            auto result = static_cast<PA_Variable *>(eb->fPtr2);
            if(eb->fParam1 == 1007)
            {
                assert(eb->fParam2 == 2);
                checkString(args[0]->uValue.fString, CUTF16String({'c','b'}));
                checkString(args[1]->uValue.fString, expected);
                *result = resultVariable();
                ++calls;
            }else if(eb->fParam1 == 1231){
                PA_SetBooleanVariable(result, propertyPresent);
            }else if(eb->fParam1 == 1217){
                assert(eb->fParam2 == 1);
                assert(references.count(static_cast<Reference *>(args[0]->uValue.fObject)));
                *result = resultVariable();
            }else{
                assert(false);
            }
            break;
        }
        case EX_GET_OBJ_VALUE:
            *static_cast<PA_Variable *>(eb->fPtr2) = copyVariable(property);
            break;
        case EX_SET_OBJ_VALUE:
            clear(&stored);
            stored = copyVariable(*static_cast<PA_Variable *>(eb->fPtr2));
            break;
        default:
            fprintf(stderr, "Unexpected engine selector %d\n", selector);
            abort();
    }
}

void balanced()
{
    assert(strings.empty() && "unreleased SDK string");
    assert(handles.empty() && "unreleased SDK handle");
    assert(references.empty() && "unreleased SDK reference");
}

std::vector<CUTF16String> fixtures()
{
    return {CUTF16String({'A','S','C','I','I'}),
            CUTF16String({0x65e5, 0x672c}),
            CUTF16String({0xd83d, 0xde00}), CUTF16String()};
}

CUTF8String utf8(const CUTF16String &text)
{
    CUTF8String exact;
    if(text == CUTF16String({'A','S','C','I','I'}))
        exact = CUTF8String({'A','S','C','I','I'});
    else if(text == CUTF16String({0x65e5, 0x672c}))
        exact = CUTF8String({0xe6, 0x97, 0xa5, 0xe6, 0x9c, 0xac});
    else if(text == CUTF16String({0xd83d, 0xde00}))
        exact = CUTF8String({0xf0, 0x9f, 0x98, 0x80});
    else
        assert(text.empty());
    C_TEXT value;
    value.setUTF16String(text.c_str(), text.size());
    CUTF8String result;
    value.copyUTF8String(&result);
    assert(result == exact);
    return result;
}

void callbacks(bool direct)
{
    for(bool allocated : {false, true})
    for(auto kind : {eVK_Undefined, eVK_Unistring, eVK_Object, eVK_Collection})
    for(const auto &text : fixtures())
    {
        allocatedEmpty = allocated;
        directMethod = direct;
        returnKind = kind;
        expected = text;
        mount::LISTENER_METHOD.setUTF16String(CUTF16String({'c','b'}).c_str(), 2);
        mount::USER_INFO.push_back(text);
        unsigned before = calls;
        listenerLoopExecuteMethod();
        assert(calls == before + 1 && mount::USER_INFO.empty());
        balanced();
        listenerLoopExecuteMethod();
        assert(calls == before + 1);
    }
}

void properties()
{
    auto obj = reinterpret_cast<PA_ObjectRef>(1);
    for(bool allocated : {false, true})
    for(const auto &text : fixtures())
    {
        allocatedEmpty = allocated;
        property.fType = eVK_Unistring;
        property.uValue.fString = makeString(text.c_str());
        CUTF8String output;
        assert(ob_get_a(obj, L"key", &output));
        assert(output == utf8(text));
        checkString(property.uValue.fString, text);
        assert(!ob_get_b(obj, L"key"));
        assert(ob_get_n(obj, L"key") == 0);
        assert(!ob_get_c(obj, L"key"));
        assert(!ob_get_o(obj, L"key"));
        clear(&property);
        balanced();
    }
    for(auto kind : {eVK_Object, eVK_Collection})
    {
        property.fType = kind;
        Reference *ref = newReference();
        property.uValue.fObject = ref;
        CUTF8String unchanged({1, 2});
        assert(ob_get_a(obj, L"key", &unchanged));
        assert(unchanged == CUTF8String({1, 2}));
        assert(!ob_get_b(obj, L"key"));
        assert(ob_get_n(obj, L"key") == 0);
        if(kind == eVK_Object)
        {
            assert(!ob_get_c(obj, L"key"));
            auto result = ob_get_o(obj, L"key");
            assert(result == ref && ref->count == 2);
            clear(&property);
            assert(references.count(ref) && ref->count == 1);
            PA_DisposeObject(result);
        }else{
            assert(!ob_get_o(obj, L"key"));
            auto result = ob_get_c(obj, L"key");
            assert(result == ref && ref->count == 2);
            clear(&property);
            assert(references.count(ref) && ref->count == 1);
            PA_DisposeCollection(result);
        }
        balanced();
    }
    property = PA_CreateVariable(eVK_Boolean);
    PA_SetBooleanVariable(&property, true);
    assert(ob_get_b(obj, L"key"));
    property = PA_CreateVariable(eVK_Real);
    PA_SetRealVariable(&property, 12.5);
    assert(ob_get_n(obj, L"key") == 12.5);
    propertyPresent = false;
    CUTF8String output({1});
    assert(!ob_get_a(obj, L"missing", &output) && output == CUTF8String({1}));
    assert(!ob_get_b(obj, L"missing") && ob_get_n(obj, L"missing") == 0);
    assert(!ob_get_o(obj, L"missing") && !ob_get_c(obj, L"missing"));
    balanced();
}

void setters()
{
    Reference *ref = newReference();
    auto obj = static_cast<PA_ObjectRef>(ref);
    for(bool allocated : {false, true})
    for(const auto &text : fixtures())
    {
        allocatedEmpty = allocated;
        CUTF8String narrow = utf8(text);
        ob_set_a(obj, L"key", &text);
        checkString(stored.uValue.fString, text);
        clear(&stored);
        ob_set_s(obj, "key", reinterpret_cast<const char *>(narrow.c_str()));
        checkString(stored.uValue.fString, text);
        clear(&stored);
        ob_set_s(obj, L"key", reinterpret_cast<const char *>(narrow.c_str()));
        checkString(stored.uValue.fString, text);
        clear(&stored);
        returnKind = eVK_Unistring;
        expected = text;
        CUTF8String output;
        ob_stringify(obj, &output);
        assert(output == narrow && ref->count == 1);
        assert(strings.empty() && handles.empty() && references.size() == 1);
    }
    ob_set_a(obj, L"key", L"\u65e5\U0001f600");
    checkString(stored.uValue.fString, CUTF16String({0x65e5, 0xd83d, 0xde00}));
    clear(&stored);
    for(auto kind : {eVK_Object, eVK_Collection})
    {
        Reference *child = newReference();
        if(kind == eVK_Object) ob_set_o(obj, L"key", child);
        else ob_set_c(obj, L"key", child);
        assert(stored.fType == kind && stored.uValue.fObject == child);
        assert(child->count == 1);
        clear(&stored);
        assert(references.size() == 1 && ref->count == 1);
    }
    for(auto kind : {eVK_Object, eVK_Collection})
    {
        returnKind = kind;
        CUTF8String unchanged({1});
        ob_stringify(obj, &unchanged);
        assert(unchanged == CUTF8String({1}) && ref->count == 1);
    }
    PA_DisposeObject(obj);
    balanced();
}

void arrays()
{
    for(bool allocated : {false, true})
    {
        allocatedEmpty = allocated;
        PA_Variable array = PA_CreateVariable(eVK_ArrayUnicode);
        PA_ResizeArray(&array, 3);
        auto texts = fixtures();
        for(int i = 0; i < 4; ++i)
        {
            PA_Unistring value = PA_CreateUnistring(const_cast<PA_Unichar *>(texts[i].c_str()));
            PA_SetStringInArray(array, i, &value);
        }
        PackagePtr params = reinterpret_cast<PackagePtr>(new PA_Variable *[1]{&array});
        {
            ARRAY_TEXT copy;
            copy.fromParamAtIndex(params, 1);
            PA_ResizeArray(&array, 0);
            PA_ClearVariable(&array);
            array = PA_CreateVariable(eVK_ArrayUnicode);
            copy.toParamAtIndex(params, 1);
            for(int i = 0; i < 4; ++i)
                checkString(PA_GetStringInArray(array, i), texts[i]);
            copy.toParamAtIndex(params, 1);
            for(int i = 0; i < 4; ++i)
                checkString(PA_GetStringInArray(array, i), texts[i]);
        }
        delete[] reinterpret_cast<PA_Variable **>(params);
        PA_ClearVariable(&array);
        for(int scenario = 0; scenario < 4; ++scenario)
        {
            PA_Variable rejected = PA_CreateVariable(eVK_ArrayUnicode);
            if(scenario == 0) rejected.fType = eVK_Longint;
            PA_Handle data = rejected.uValue.fArray.fData;
            if(scenario == 3) rejected.uValue.fArray.fData = nullptr;
            PA_Unistring value = PA_CreateUnistring(const_cast<PA_Unichar *>(texts[0].c_str()));
            PA_SetStringInArray(rejected, scenario == 1 ? -1 : 1, &value);
            checkString(value, texts[0]);
            PA_DisposeUnistring(&value);
            rejected.fType = eVK_ArrayUnicode;
            rejected.uValue.fArray.fData = data;
            PA_SetStringInArray(rejected, 0, nullptr);
            PA_ClearVariable(&rejected);
        }
        balanced();
    }
}
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    gCall4D = engine;
    @autoreleasepool {
        if(!strcmp(argv[1], "callbacks-direct")) callbacks(true);
        else if(!strcmp(argv[1], "callbacks-fallback")) callbacks(false);
        else if(!strcmp(argv[1], "properties")) properties();
        else if(!strcmp(argv[1], "setters")) setters();
        else if(!strcmp(argv[1], "arrays")) arrays();
        else abort();
    }
    balanced();
}
